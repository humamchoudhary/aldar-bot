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
import queue
import numpy as np

# Load environment variables
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")

# Endpoint to send logs after call ends
LOG_ENDPOINT = os.getenv("LOG_ENDPOINT", "https://al-dar.go-globe.dev/call/log")
SYS_INST_ENDPOINT = os.getenv("SYS_INST_ENDPOINT", "https://al-dar.go-globe.dev/call/get-files")

# Configure chunk size for incremental logging
LOG_CHUNK_SIZE = int(os.getenv("LOG_CHUNK_SIZE", "5"))  # Send logs every 5 messages by default

# Barge-in configuration
BARGE_IN_ENABLED = os.getenv("BARGE_IN_ENABLED", "true").lower() == "true"
VAD_ENERGY_THRESHOLD = int(os.getenv("VAD_ENERGY_THRESHOLD", "500"))
VAD_SILENCE_DURATION = float(os.getenv("VAD_SILENCE_DURATION", "0.3"))

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
        self.custom_params = {}

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

        # ---- Barge-in/Interruption control ----
        self.is_gemini_speaking = False
        self.interrupt_requested = False
        self.user_is_speaking = False
        self.consecutive_speech_frames = 0
        self.consecutive_silence_frames = 0
        self.last_audio_chunk = b""
        
        # Voice Activity Detection (VAD) parameters
        self.vad_energy_threshold = VAD_ENERGY_THRESHOLD
        self.vad_silence_frames_threshold = int(VAD_SILENCE_DURATION * 50)  # 50 frames per second
        self.vad_speech_frames_threshold = 3  # Minimum frames to consider as speech
        
        # Audio buffer for real-time processing
        self.audio_chunks = []
        self.audio_buffer_size = 20  # Buffer last 20 chunks for interruption handling
        
        # ---- System instruction ----
        self.system_instruction = """
        You are a professional AI assistant trained in customer service and sales communication.
        Respond concisely (1–3 lines) based only on the uploaded company profile. always respond with the language the user is speaking in
        """
        self.get_system_instruction()

        # ---- Model config ----
        self.config = {
            "response_modalities": ["AUDIO"],
            "thinking_config": {"thinking_budget": 0},
            "output_audio_transcription": {},
            "input_audio_transcription": {},
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
            },
            "systemInstruction": self.system_instruction,
            "tools": [{"function_declarations": [
                {
                    "name": "get_branch_details",
                    "description": "Get details of all Aldar Exchange branch locations including addresses, phone numbers, working hours, and coordinates.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                },
                {
                    "name": "calculate_exchange",
                    "description": "Calculate currency conversion between QAR and foreign currency. Specify either local currency amount (QAR) or foreign currency amount, not both.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "transaction_type": {
                                "type": "string",
                                "description": "Transaction type: 'tt' for transfer, 'BUY' for buying currency, 'SELL' for selling currency",
                                "enum": ["tt", "BUY", "SELL"]
                            },
                            "currency_code": {
                                "type": "string",
                                "description": "3-letter ISO currency code (e.g., USD, EUR, GBP)"
                            },
                            "local_amount": {
                                "type": "number",
                                "description": "Amount in local currency (will always QAR or qatari riyal). Use 0 if specifying foreign amount."
                            },
                            "foreign_amount": {
                                "type": "number",
                                "description": "Amount in foreign currency. Use 0 if specifying local amount."
                            }
                        },
                        "required": ["transaction_type", "currency_code", "local_amount", "foreign_amount"]
                    }
                },
                {
                    "name": "get_transaction_status",
                    "description": "Get the status of a transaction using its reference number. Returns transaction status, message, and additional details if available.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "transaction_ref_no": {
                                "type": "string",
                                "description": "The transaction reference number (e.g., 63897333251760, 1882910250001460)"
                            }
                        },
                        "required": ["transaction_ref_no"]
                    }
                },
                {
                    "name": "transfer_to_human_operator",
                    "description": "Transfer the call to a human operator when the user requests to speak with a person, representative, or human agent. Use this when user explicitly asks to talk to someone or cannot be helped by the AI.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {
                                "type": "string",
                                "description": "Brief reason for the transfer (e.g., 'customer requested human agent', 'complex query requiring human assistance')"
                            }
                        },
                        "required": ["reason"]
                    }
                }
            ]}]
        }

    def _call_aldar_api(self, function_name, parameters):
        """Execute actual API calls to Aldar Exchange"""
        try:
            if function_name == "get_exchange_rate":
                rate_type = parameters.get("rate_type", 1)
                url = f"{self.aldar_base_url}/api/User/GetRate"
                response = requests.get(url, params={"type": rate_type})
                response.raise_for_status()
                return response.json()
            
            elif function_name == "get_branch_details":
                url = f"{self.aldar_base_url}/api/User/GetBranchesDetails"
                response = requests.get(url)
                response.raise_for_status()
                branches = response.json()
                # Wrap list in dictionary as Gemini expects dict response
                return {"branches": branches, "total_count": len(branches)}
            
            elif function_name == "calculate_exchange":
                url = f"{self.aldar_base_url}/api/User/GetRate"
                params = {
                    "type": parameters.get("transaction_type"),
                    "curcode": parameters.get("currency_code"),
                    "lcyamount": parameters.get("local_amount", 0),
                    "fcyamount": parameters.get("foreign_amount", 0)
                }
                response = requests.get(url, params=params)
                response.raise_for_status()
                return response.json()

            elif function_name == "get_transaction_status":
                tran_ref_no = parameters.get("transaction_ref_no")
                url = f"{self.aldar_base_url}/api/User/GetTransactionDetails"
                response = requests.get(url, params={"tranRefNo": tran_ref_no})
                response.raise_for_status()
                return response.json()
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API call failed: {str(e)}"}

    def get_system_instruction(self):
        try:
            resp = requests.get(SYS_INST_ENDPOINT, verify=False)
            if resp.status_code == 200:
                self.system_instruction += f"\n\nAdditional Data:\n{resp.text}"
                print("✅ Loaded system instruction successfully.")
            else:
                raise Exception("Could not fetch system instruction")
            print(self.system_instruction)
        except Exception as e:
            print(f"⚠️ Failed to load system instruction: {e}")

    def detect_voice_activity(self, audio_chunk):
        """Simple voice activity detection based on audio energy"""
        if len(audio_chunk) < 4:
            return False
        
        # Calculate RMS energy
        rms_energy = audioop.rms(audio_chunk, 2)
        
        # Dynamic threshold adjustment (optional)
        if rms_energy > self.vad_energy_threshold:
            self.consecutive_speech_frames += 1
            self.consecutive_silence_frames = 0
        else:
            self.consecutive_silence_frames += 1
            if self.consecutive_silence_frames > self.vad_speech_frames_threshold * 2:
                self.consecutive_speech_frames = 0
        
        # Update user speaking state
        was_speaking = self.user_is_speaking
        self.user_is_speaking = self.consecutive_speech_frames >= self.vad_speech_frames_threshold
        
        # Return detection result
        if not was_speaking and self.user_is_speaking:
            return "speech_start"
        elif self.user_is_speaking:
            return "speech_ongoing"
        elif was_speaking and not self.user_is_speaking:
            return "speech_end"
        
        return "silence"

    async def initialize_call(self):
        """Send initial POST request to create call session at the start."""
        try:
            init_url = f"{LOG_ENDPOINT}/{self.call_uuid}"
            payload = {
                "call_uuid": self.call_uuid,
                "file_name": self.filename,
                "started_at": datetime.datetime.now().isoformat(),
                "custom_params": self.custom_params
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
                    self.custom_params = data["start"]["customParameters"]
                    print(data)
                    print(f"📡 Twilio stream started: {self.stream_sid} -> {self.custom_params}")

                    await self.initialize_call()

                elif event == "media":
                    audio_b64 = data["media"]["payload"]
                    mulaw_bytes = base64.b64decode(audio_b64)
                    pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
                    pcm_16k, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                    
                    # Store for VAD and interruption detection
                    self.last_audio_chunk = pcm_16k
                    self.audio_chunks.append(pcm_16k)
                    if len(self.audio_chunks) > self.audio_buffer_size:
                        self.audio_chunks.pop(0)
                    
                    # Voice Activity Detection
                    if BARGE_IN_ENABLED:
                        vad_result = self.detect_voice_activity(pcm_16k)
                        
                        # Check for user interruption during Gemini speech
                        if vad_result in ["speech_start", "speech_ongoing"] and self.is_gemini_speaking:
                            print(f"🎤 User speaking during Gemini response (VAD: {vad_result})")
                            # Set interruption flag - will be handled in gemini_session
                            self.interrupt_requested = True
                    
                    # Write to WAV file
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
        """Bridges Twilio audio and Gemini responses with interruption support."""
        print(f"✅ Starting Gemini session for {self.call_uuid}")

        async with self.client.aio.live.connect(model=self.model_id, config=self.config) as session:
            bot_buffer = ""
            gemini_response_audio = b""
            last_interruption_check = asyncio.get_event_loop().time()
            
            try:
                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(),
                    mime_type="audio/pcm;rate=16000"
                ):
                    # Check for user interruption periodically
                    current_time = asyncio.get_event_loop().time()
                    if BARGE_IN_ENABLED and current_time - last_interruption_check > 0.1:  # Check every 100ms
                        if self.interrupt_requested and self.is_gemini_speaking:
                            print("🛑 INTERRUPTION DETECTED - Handling user barge-in")
                            
                            # Send a mark event to Twilio to indicate interruption boundary
                            if self.stream_sid:
                                await websocket.send(json.dumps({
                                    "event": "mark",
                                    "streamSid": self.stream_sid,
                                    "mark": {"name": "interruption"}
                                }))
                            
                            # Clear any buffered bot response
                            bot_buffer = ""
                            gemini_response_audio = b""
                            
                            # Reset interruption flag
                            self.interrupt_requested = False
                            
                            # Note: We can't directly stop the Gemini stream, but we can
                            # ignore further audio from this response and wait for next input
                        
                        last_interruption_check = current_time

                    # Handle tool calls
                    if response.tool_call:
                        print("------ Function Called --------")
                        func_resps = []
                        print(response.tool_call)
                        for fc in response.tool_call.function_calls:
                            if fc.name == "transfer_to_human_operator":
                                print("Transfer to human")
                                # Clear any pending audio before transfer
                                if self.stream_sid and gemini_response_audio:
                                    b64_audio = self.convert_audio_to_twilio_format(gemini_response_audio)
                                    await websocket.send(json.dumps({
                                        "event": "media",
                                        "streamSid": self.stream_sid,
                                        "media": {"payload": b64_audio}
                                    }))
                                    gemini_response_audio = b""
                                
                                await session.close()
                                return
                            
                            resp = self._call_aldar_api(function_name=fc.name, parameters=fc.args)
                            print(resp)
                            function_response = types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response=resp
                            )
                            func_resps.append(function_response)

                        await session.send_tool_response(function_responses=func_resps)

                    # Handle Gemini -> Twilio audio
                    if response.data:
                        self.is_gemini_speaking = True
                        gemini_response_audio += response.data
                        
                        # Only send audio if no interruption is requested
                        if not self.interrupt_requested:
                            pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                            self.merged_wav.writeframes(pcm_16k)

                            if self.stream_sid:
                                b64_audio = self.convert_audio_to_twilio_format(response.data)
                                await websocket.send(json.dumps({
                                    "event": "media",
                                    "streamSid": self.stream_sid,
                                    "media": {"payload": b64_audio}
                                }))
                        else:
                            # If interruption was requested, skip sending this audio chunk
                            print("⏸️ Skipping audio chunk due to interruption")

                    # Handle transcriptions
                    if response.server_content and response.server_content.input_transcription:
                        user_text = response.server_content.input_transcription.text
                        print("👤 User:", user_text)
                        self.transcriptions.append({"name": "user", "transcription": user_text})

                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            bot_buffer = ""

                        if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                            await self.send_log_chunk()

                    if response.server_content and response.server_content.output_transcription:
                        chunk = response.server_content.output_transcription.text
                        print("🤖 Bot chunk:", chunk)
                        bot_buffer += " " + chunk.strip()

                    if response.server_content and response.server_content.model_turn:
                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            print("🤖 Bot complete:", bot_buffer.strip())
                            bot_buffer = ""
                            if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                                await self.send_log_chunk()
                        
                        # End of Gemini's turn
                        self.is_gemini_speaking = False
                        gemini_response_audio = b""
                        
                        # Reset interruption flag at turn end
                        self.interrupt_requested = False
                        
            except Exception as e:
                print(f"❌ Error in gemini_session: {e}")

            finally:
                # Send any remaining bot transcription
                if bot_buffer.strip():
                    self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                
                # Send any remaining audio
                if self.stream_sid and gemini_response_audio:
                    b64_audio = self.convert_audio_to_twilio_format(gemini_response_audio)
                    await websocket.send(json.dumps({
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": b64_audio}
                    }))
                
                self.merged_wav.close()
                await self.send_log_chunk(is_final=True)
                
                try:
                    await websocket.close(code=200)
                except:
                    pass
                
                print(f"🏁 Call session {self.call_uuid} ended cleanly.")


@app.websocket('/')
async def media_stream():
    """Main WebSocket endpoint for Twilio Media Stream."""
    print("🚀 Twilio WebSocket connected.")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()


if __name__ == "__main__":
    port = os.getenv('CALL_WEBRTC_URL')
    app.run(host="0.0.0.0", port=3059)
