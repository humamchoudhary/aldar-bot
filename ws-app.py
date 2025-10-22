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



active_calls = {} 

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
        Respond concisely (1–3 lines) based only on the uploaded company profile.
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
            "systemInstruction":self.system_instruction,

            "tools":[{"function_declarations":[
                        {
                            "name": "get_exchange_rate",
                            "description": "Get the current exchange rate for a specific rate type. Use type=1 for standard rates.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "rate_type": {
                                        "type": "integer",
                                        "description": "The rate type code (e.g., 1 for standard rate)"
                                    }
                                },
                                "required": ["rate_type"]
                            }
                        },
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
                                        "description": "Amount in local currency (QAR). Use 0 if specifying foreign amount."
                                    },
                                    "foreign_amount": {
                                        "type": "number",
                                        "description": "Amount in foreign currency. Use 0 if specifying local amount."
                                    }
                                },
                                "required": ["transaction_type", "currency_code", "local_amount", "foreign_amount"]
                            }
                        }
                    ]}]
        }

        self.admin_mode = False
        self.admin_ws = None
        self.twilio_ws = None  # Store Twilio WebSocket reference
    
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
                    print(f"📡 Twilio stream started: {self.stream_sid}")
                    print(f"👤 Customer info: {self.custom_params}")
                    
                    active_calls[self.call_uuid] = self
                    await self.initialize_call()

                elif event == "media":
                    audio_b64 = data["media"]["payload"]
                    mulaw_bytes = base64.b64decode(audio_b64)
                    pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
                    pcm_16k, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                    self.merged_wav.writeframes(pcm_16k)
                    
                    # Send customer audio to admin if in admin mode
                    if self.admin_mode and self.admin_ws:
                        await self.send_audio_to_admin(pcm_16k)
                    
                    # Only yield to Gemini if NOT in admin mode
                    if not self.admin_mode:
                        yield pcm_16k

                elif event == "stop":
                    print("🛑 Twilio stream stopped.")
                    break
                    
            except Exception as e:
                print(f"❌ Error in twilio_audio_stream: {e}")
                break

    async def send_audio_to_admin(self, pcm_data):
        """Send customer audio to admin WebSocket."""
        try:
            if self.admin_ws:
                b64_audio = base64.b64encode(pcm_data).decode('utf-8')
                await self.admin_ws.send(json.dumps({
                    "type": "customer_audio",
                    "audio": b64_audio
                }))
                # print("📤 Sent customer audio to admin")  # Too verbose
        except Exception as e:
            print(f"❌ Error sending audio to admin: {e}")
            self.admin_mode = False
            self.admin_ws = None

    async def send_audio_to_customer(self, pcm_16k_data):
        """Send audio to customer via Twilio."""
        try:
            if self.stream_sid:
                # Convert PCM 16kHz to Twilio format (8kHz µ-law)
                pcm_8k, _ = audioop.ratecv(pcm_16k_data, 2, 1, 16000, 8000, None)
                mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
                b64_audio = base64.b64encode(mulaw_data).decode("utf-8")
                
                # Send via the main Twilio WebSocket
                await websocket.send(json.dumps({
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": b64_audio}
                }))
                # print("🎤 Sent audio to customer")  # Too verbose
        except Exception as e:
            print(f"❌ Error sending audio to customer: {e}")

    async def admin_takeover(self, admin_websocket):
        """Switch from Gemini to Admin mode."""
        print(f"👔 Admin taking over call {self.call_uuid}")
        self.admin_mode = True
        self.admin_ws = admin_websocket
        
        # Notify admin
        try:
            await self.admin_ws.send(json.dumps({
                "type": "takeover_success",
                "call_uuid": self.call_uuid,
                "customer_info": self.custom_params
            }))
        except Exception as e:
            print(f"❌ Failed to send takeover confirmation: {e}")
            return
        
        # Add transcription note
        self.transcriptions.append({
            "name": "system",
            "transcription": "Admin has joined the call"
        })
        
        # Keep admin connection alive and handle audio
        try:
            while self.admin_mode:
                try:
                    msg = await asyncio.wait_for(self.admin_ws.receive(), timeout=0.1)
                    data = json.loads(msg)
                    
                    if data.get("type") == "admin_audio":
                        # Admin is speaking, send to customer
                        audio_b64 = data.get("audio")
                        if audio_b64:
                            pcm_data = base64.b64decode(audio_b64)
                            await self.send_audio_to_customer(pcm_data)
                    
                    elif data.get("type") == "end_takeover":
                        print("👔 Admin ending takeover")
                        await self.end_admin_takeover()
                        break
                        
                except asyncio.TimeoutError:
                    # No message received, continue
                    await asyncio.sleep(0.01)
                    continue
                    
        except Exception as e:
            print(f"❌ Admin connection error: {e}")
            await self.end_admin_takeover()

    async def end_admin_takeover(self):
        """Return call to Gemini control."""
        print(f"🤖 Returning call {self.call_uuid} to Gemini")
        self.admin_mode = False
        
        if self.admin_ws:
            try:
                await self.admin_ws.send(json.dumps({
                    "type": "takeover_ended"
                }))
            except:
                pass
            self.admin_ws = None
        
        self.transcriptions.append({
            "name": "system",
            "transcription": "Admin has left, AI resumed"
        })

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

        async with self.client.aio.live.connect(model=self.model_id, config=self.config) as session:
            bot_buffer = ""
            try:
                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(),
                    mime_type="audio/pcm;rate=16000"
                ):

                    # Skip Gemini processing when in admin mode
                    if self.admin_mode:
                        continue 

                    if response.tool_call:
                        print("------ Function Called --------")
                        func_resps = []
                        for fc in response.tool_call.function_calls:
                            resp = self._call_aldar_api(function_name=fc.name,parameters=fc.args)
                            function_response = types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response=resp
                            )
                            func_resps.append(function_response)

                        await session.send_tool_response(function_responses=func_resps)

                    # Handle Gemini -> Twilio audio (only when NOT in admin mode)
                    if response.data and not self.admin_mode:
                        pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                        self.merged_wav.writeframes(pcm_16k)

                        if self.stream_sid:
                            b64_audio = self.convert_audio_to_twilio_format(response.data)
                            await websocket.send(json.dumps({
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": {"payload": b64_audio}
                            }))

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

                if self.call_uuid in active_calls:
                    del active_calls[self.call_uuid]

                await websocket.close(code=200)
                print(f"🏁 Call session {self.call_uuid} ended cleanly.")





@app.websocket('/admin')
async def admin_websocket():
    """WebSocket endpoint for admin to join calls."""
    print("👔 Admin WebSocket connected.")
    try:
        while True:  # Keep connection alive
            # Wait for admin messages
            msg = await websocket.receive()
            data = json.loads(msg)
            
            if data.get("action") == "list_calls":
                # Send list of active calls
                calls_list = [
                    {
                        "call_uuid": uuid,
                        "customer_info": bridge.custom_params,
                        "duration": "active"
                    }
                    for uuid, bridge in active_calls.items()
                ]
                await websocket.send(json.dumps({
                    "type": "active_calls",
                    "calls": calls_list
                }))
                print(f"📋 Sent {len(calls_list)} active calls to admin")
            
            elif data.get("action") == "join_call":
                call_uuid = data.get("call_uuid")
                print(f"👔 Admin requesting to join call: {call_uuid}")
                
                if call_uuid in active_calls:
                    bridge = active_calls[call_uuid]
                    await bridge.admin_takeover(websocket)
                    # admin_takeover will keep running until admin leaves
                    break  # Exit the loop when admin disconnects
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Call not found or already ended"
                    }))
                    
    except Exception as e:
        print(f"❌ Admin WebSocket error: {e}")
    finally:
        print("👔 Admin WebSocket disconnected")



@app.websocket('/')
async def media_stream():
    """Main WebSocket endpoint for Twilio Media Stream."""
    print("🚀 Twilio WebSocket connected.")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3059)
