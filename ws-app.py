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
LOG_ENDPOINT = os.getenv("LOG_ENDPOINT", "https://al-dar.go-globe.dev/call/log")
SYS_INST_ENDPOINT = os.getenv("SYS_INST_ENDPOINT", "https://al-dar.go-globe.dev/call/get-files")

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
            "realtime_input_config": {
        "automatic_activity_detection": {
            "disabled": False, # default
            "start_of_speech_sensitivity": types.StartSensitivity.START_SENSITIVITY_LOW,
            "end_of_speech_sensitivity": types.EndSensitivity.END_SENSITIVITY_LOW,
            "prefix_padding_ms": 20,
            "silence_duration_ms": 100,
        }
    },
             "speech_config": {
                    "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
                },
            "systemInstruction":self.system_instruction,

            "tools":[{"function_declarations":[
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

    async def initialize_call(self):
        """Send initial POST request to create call session at the start."""
        try:
            init_url = f"{LOG_ENDPOINT}/{self.call_uuid}"
            payload = {
                "call_uuid": self.call_uuid,
                "file_name": self.filename,
                "started_at": datetime.datetime.now().isoformat(),
                "custom_params":self.custom_params
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
        """Bridges Twilio audio and Gemini responses with proper interruption handling."""
        print(f"✅ Starting Gemini session for {self.call_uuid}")

        async with self.client.aio.live.connect(model=self.model_id, config=self.config) as session:
            bot_buffer = ""
            is_bot_speaking = False
            last_turn_complete = False
            interruption_count = 0
            
            try:
                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(),
                    mime_type="audio/pcm;rate=16000"
                ):
                    # ---- CRITICAL: Handle interruption FIRST ----
                    if response.server_content and response.server_content.interrupted:
                        interruption_count += 1
                        print(f"⚠️ INTERRUPTION #{interruption_count} DETECTED - Stopping bot audio")
                        
                        # Clear Twilio's audio buffer immediately
                        if self.stream_sid:
                            try:
                                await websocket.send(json.dumps({
                                    "event": "clear",
                                    "streamSid": self.stream_sid
                                }))
                                print("✅ Sent clear event to Twilio")
                            except Exception as e:
                                print(f"❌ Error sending clear: {e}")
                        
                        # Reset bot speaking state
                        is_bot_speaking = False
                        
                        # Save partial transcription if any
                        if bot_buffer.strip():
                            self.transcriptions.append({
                                "name": "bot", 
                                "transcription": bot_buffer.strip() + " [interrupted]"
                            })
                            print(f"💾 Saved interrupted transcription: {bot_buffer.strip()[:50]}...")
                            bot_buffer = ""
                        
                        # Mark that we need to wait for model turn to complete
                        last_turn_complete = False
                        
                        # Continue listening - DON'T skip other response processing
                        # The user input that caused the interrupt may be in this response
                        # continue

                    # ---- Handle tool calls ----
                    if response.tool_call:
                        print("------ Function Called --------")
                        func_resps = []
                        print(response.tool_call)
                        
                        for fc in response.tool_call.function_calls:
                            if fc.name == "transfer_to_human_operator":
                                print("Transfer to human operator")
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

                    # ---- Handle Gemini audio output ----
                    # Only send audio if NOT interrupted and bot should be speaking
                    if response.data:
                        # Check if this is stale audio after interruption
                        if response.server_content and response.server_content.interrupted:
                            print("🚫 Skipping audio chunk - interrupted")
                            # Still write to WAV for recording
                            pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                            self.merged_wav.writeframes(pcm_16k)
                            continue
                        
                        # Mark that bot is speaking when audio starts
                        if not is_bot_speaking:
                            is_bot_speaking = True
                            last_turn_complete = False
                            print("🤖 Bot started speaking")
                        
                        # Always write to WAV for recording
                        pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                        self.merged_wav.writeframes(pcm_16k)

                        # Send to Twilio only if bot should be speaking
                        if self.stream_sid and is_bot_speaking:
                            b64_audio = self.convert_audio_to_twilio_format(response.data)
                            await websocket.send(json.dumps({
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": {"payload": b64_audio}
                            }))

                    # ---- Handle user transcriptions (input) ----
                    if response.server_content and response.server_content.input_transcription:
                        user_text = response.server_content.input_transcription.text
                        print(f"👤 User: {user_text}")
                        
                        # If bot was speaking and user started talking, note it
                        if is_bot_speaking:
                            print("⚠️ User spoke while bot was talking - potential interrupt")
                        
                        self.transcriptions.append({"name": "user", "transcription": user_text})

                        # Save any pending bot transcription
                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            bot_buffer = ""

                        # Send log chunk if threshold reached
                        if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                            await self.send_log_chunk()

                    # ---- Handle bot transcriptions (output) ----
                    if response.server_content and response.server_content.output_transcription:
                        # Skip transcription if interrupted
                        if response.server_content.interrupted:
                            print("🚫 Skipping transcription chunk - interrupted")
                            continue
                            
                        chunk = response.server_content.output_transcription.text
                        print(f"🤖 Bot chunk: {chunk}")
                        bot_buffer += " " + chunk.strip()

                    # ---- Handle model turn completion ----
                    if response.server_content and response.server_content.model_turn:
                        is_bot_speaking = False
                        last_turn_complete = True
                        print(f"✅ Bot finished speaking (turn #{interruption_count + 1} complete)")
                        
                        if bot_buffer.strip():
                            self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                            print(f"🤖 Bot complete: {bot_buffer.strip()[:100]}...")
                            bot_buffer = ""
                            
                            if len(self.transcriptions) - self.last_sent_index >= LOG_CHUNK_SIZE:
                                await self.send_log_chunk()
                    
                    # ---- Handle turn completion after interruption ----
                    if response.server_content and response.server_content.turn_complete:
                        print("🔄 Turn complete - ready for next interaction")
                        is_bot_speaking = False
                        last_turn_complete = True
                                
            except Exception as e:
                print(f"❌ Error in gemini_session: {e}")
                import traceback
                traceback.print_exc()

            finally:
                # Save any remaining transcription
                if bot_buffer.strip():
                    self.transcriptions.append({"name": "bot", "transcription": bot_buffer.strip()})
                
                # Close WAV file and send final logs
                self.merged_wav.close()
                await self.send_log_chunk(is_final=True)
                await websocket.close(code=200)
                print(f"🏁 Call session {self.call_uuid} ended. Total interruptions: {interruption_count}")


@app.websocket('/')
async def media_stream():
    """Main WebSocket endpoint for Twilio Media Stream."""
    print("🚀 Twilio WebSocket connected.")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()


if __name__ == "__main__":
    port = os.getenv('CALL_WEBRTC_URL')
    app.run(host="0.0.0.0", port=8000)
