from uuid import uuid4
import os
import json
import base64
import audioop
import wave
import aiohttp
import asyncio
import datetime
from quart import Quart, websocket
from google import genai
from google.genai import types
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")

# Endpoint to send logs after call ends
LOG_ENDPOINT = os.getenv("LOG_ENDPOINT", "https://192.168.100.4:5000/call/log")
SYS_INST_ENDPOINT = os.getenv("SYS_INST_ENDPOINT", "https://192.168.100.4:5000/call/get-files")

# Configure chunk size for incremental logging
LOG_CHUNK_SIZE = int(os.getenv("LOG_CHUNK_SIZE", "5"))  # Send logs every 5 messages by default

app = Quart(__name__)


class GeminiTwilioBridge:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_KEY"))
        self.model_id = "gemini-2.5-flash-native-audio-latest"

        # ---- Unique per-call identifiers ----
        self.call_uuid = str(uuid4())
        self.transcriptions = []
        self.last_sent_index = 0
        self.unsent_transcriptions = []
        self.stream_sid = None

        # ---- Create per-call WAV file ----
        os.makedirs("recordings", exist_ok=True)
        self.filename = os.path.join("recordings", f"call_{self.call_uuid}.wav")
        self.merged_wav = wave.open(self.filename, "wb")
        self.merged_wav.setnchannels(1)
        self.merged_wav.setsampwidth(2)
        self.merged_wav.setframerate(16000)

        # ---- Aldar Exchange API base URL ----
        self.aldar_base_url = os.getenv("ALDAR_BASE_API_URL")

        print(f"📁 Created file for this call: {self.filename}")

        # ---- System instruction ----
        self.system_instruction = """
        You are a professional AI assistant trained in customer service and sales communication.
        Respond concisely (1–3 lines) based only on the uploaded company profile.
        """
        self.get_system_instruction()

        # ---- Model config ----
        self.config = {
            "response_modalities": ["AUDIO"],
            "thinking_config": {"thinking_budget": 0},
            "output_audio_transcription": {},
            "input_audio_transcription": {},
            "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}},
            "systemInstruction": self.system_instruction,
        }

    def get_system_instruction(self):
        try:
            resp = requests.get(SYS_INST_ENDPOINT, verify=False)
            if resp.status_code == 200:
                self.system_instruction += f"\n\nAdditional Data:\n{resp.text}"
                print("✅ Loaded system instruction successfully.")
            else:
                raise Exception("Could not fetch system instruction")
        except Exception as e:
            print(f"⚠️ Failed to load system instruction: {e}")

    async def initialize_call(self):
        """Send initial POST request to create call session at the start."""
        try:
            init_url = f"{LOG_ENDPOINT}/{self.call_uuid}"
            payload = {
                "call_uuid": self.call_uuid,
                "file_name": self.filename,
                "started_at": datetime.datetime.now().isoformat(),
            }
            print(f"📞 Initializing call session → {init_url}")
            async with aiohttp.ClientSession() as session:
                async with session.post(init_url, json=payload, ssl=False) as resp:
                    if resp.status == 200:
                        print("✅ Call session initialized.")
                    else:
                        print(f"⚠️ Failed to initialize call: {resp.status}")
        except Exception as e:
            print(f"❌ Error initializing call: {e}")

    async def twilio_audio_stream(self):
        """Handle incoming Twilio WebSocket audio stream."""
        while True:
            try:
                message = await websocket.receive()
                data = json.loads(message)
                event = data.get("event")

                if event == "start":
                    self.stream_sid = data["start"]["streamSid"]
                    print(f"📡 Twilio stream started: {self.stream_sid}")

                elif event == "media":
                    audio_b64 = data["media"]["payload"]
                    mulaw_bytes = base64.b64decode(audio_b64)
                    pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
                    pcm_16k, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                    self.merged_wav.writeframes(pcm_16k)
                    yield pcm_16k

                elif event == "stop":
                    print("🛑 Twilio stream stopped.")
                    break
            except Exception as e:
                print(f"❌ Error in twilio_audio_stream: {e}")
                break

    def convert_audio_to_twilio_format(self, audio_data: bytes) -> str:
        """Convert Gemini PCM (24kHz) → 8kHz µ-law → base64 for Twilio."""
        pcm_8k, _ = audioop.ratecv(audio_data, 2, 1, 24000, 8000, None)
        mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
        return base64.b64encode(mulaw_data).decode("utf-8")

    async def send_log_chunk(self, is_final=False):
        """Send accumulated transcriptions to the log endpoint."""
        new_transcriptions = self.transcriptions[self.last_sent_index:]
        if not new_transcriptions and not is_final:
            return

        try:
            chunk_url = f"{LOG_ENDPOINT}/{self.call_uuid}/send_chunk"
            payload = {
                "call_uuid": self.call_uuid,
                "file_name": self.filename,
                "transcription": new_transcriptions,
                "is_final": is_final,
                "chunk_index": self.last_sent_index,
            }

            print(f"📤 Sending log chunk ({self.last_sent_index}–{len(self.transcriptions)}) → {chunk_url}")
            async with aiohttp.ClientSession() as session:
                async with session.post(chunk_url, json=payload, ssl=False) as resp:
                    if resp.status == 200:
                        print(f"✅ Sent {len(new_transcriptions)} new transcriptions.")
                        self.last_sent_index = len(self.transcriptions)
                    else:
                        print(f"⚠️ Log send failed: {resp.status}")
        except Exception as e:
            print(f"❌ Error sending log chunk: {e}")

    async def gemini_session(self):
        """Bridges Twilio audio and Gemini responses."""
        print(f"✅ Starting Gemini session for {self.call_uuid}")
        await self.initialize_call()

        async with self.client.aio.live.connect(model=self.model_id, config=self.config) as session:
            bot_buffer = ""
            try:
                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(),
                    mime_type="audio/pcm;rate=16000"
                ):
                    # Handle Gemini -> Twilio audio
                    if response.data:
                        pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                        self.merged_wav.writeframes(pcm_16k)

                        if self.stream_sid:
                            b64_audio = self.convert_audio_to_twilio_format(response.data)
                            await websocket.send(json.dumps({
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": {"payload": b64_audio}
                            }))
                            print("🎧 Sent Gemini audio chunk to Twilio")

                    # Handle transcriptions
                    if response.server_content.input_transcription:
                        user_text = response.server_content.input_transcription.text
                        print("👤 User:", user_text)
                        self.transcriptions.append({"name": "user", "transcription": user_text})

                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            bot_buffer = ""

                        if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                            await self.send_log_chunk()

                    if response.server_content.output_transcription:
                        chunk = response.server_content.output_transcription.text
                        print("🤖 Bot chunk:", chunk)
                        bot_buffer += " " + chunk.strip()

                    if response.server_content.model_turn:
                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            print("🤖 Bot complete:", bot_buffer.strip())
                            bot_buffer = ""
                            if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                                await self.send_log_chunk()
            except Exception as e:
                print(f"❌ Error in gemini_session: {e}")

            finally:
                if bot_buffer.strip():
                    self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                self.merged_wav.close()
                await self.send_log_chunk(is_final=True)
                await websocket.close(code=200)
                print(f"🏁 Call session {self.call_uuid} ended cleanly.")


@app.websocket('/')
async def media_stream():
    """Main WebSocket endpoint for Twilio Media Stream."""
    print("🚀 Twilio WebSocket connected.")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3059)
