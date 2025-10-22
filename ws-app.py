from uuid import uuid4
import os
import json
import base64
import audioop
import wave
import aiohttp
import asyncio
import datetime
from quart import Quart, websocket, request, jsonify
from google import genai
from google.genai import types
from dotenv import load_dotenv
import requests
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client as TwilioClient

# Load environment variables
load_dotenv()

# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")

# Initialize Twilio client
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, os.getenv("TWILIO_AUTH_TOKEN"))

# Endpoint to send logs after call ends
LOG_ENDPOINT = os.getenv("LOG_ENDPOINT", "https://al-dar.go-globe.dev/call/log")
SYS_INST_ENDPOINT = os.getenv("SYS_INST_ENDPOINT", "https://al-dar.go-globe.dev/call/get-files")

# Configure chunk size for incremental logging
LOG_CHUNK_SIZE = int(os.getenv("LOG_CHUNK_SIZE", "5"))

app = Quart(__name__)

active_calls = {}

class GeminiTwilioBridge:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_KEY"))
        self.model_id = "gemini-2.5-flash-native-audio-latest"

        # ---- Unique per-call identifiers ----
        self.call_uuid = str(uuid4())
        self.call_sid = None  # Twilio Call SID
        self.transcriptions = []
        self.last_sent_index = 0
        self.stream_sid = None
        self.custom_params = {}
        self.transfer_requested = False
        self.admin_stream_ready = False

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
        You are a professional AI assistant for Aldar Exchange.
        If a customer asks to speak with a human or requests human assistance, respond with:
        "I'll transfer you to one of our representatives. Please hold for a moment."
        Then immediately call the request_human_transfer function.
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
                    "name": "request_human_transfer",
                    "description": "Transfer the call to a human representative when customer requests to speak with a person",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                },
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
                    "description": "Get details of all Aldar Exchange branch locations",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                },
                {
                    "name": "calculate_exchange",
                    "description": "Calculate currency conversion",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "transaction_type": {
                                "type": "string",
                                "enum": ["tt", "BUY", "SELL"]
                            },
                            "currency_code": {"type": "string"},
                            "local_amount": {"type": "number"},
                            "foreign_amount": {"type": "number"}
                        },
                        "required": ["transaction_type", "currency_code", "local_amount", "foreign_amount"]
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
                "call_sid": self.call_sid,
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

    async def request_transfer_to_admin(self):
        """Handle transfer request from Gemini"""
        print(f"🔄 Transfer requested for call {self.call_uuid}")
        self.transfer_requested = True
        self.transcriptions.append({
            "name": "system",
            "transcription": "Customer requested human assistance - transfer initiated"
        })
        
        # Update call in Twilio to redirect to admin stream
        try:
            # The actual redirect will happen via TwiML endpoint
            # This just marks the call as ready for admin
            self.admin_stream_ready = True
            print(f"✅ Call {self.call_uuid} ready for admin takeover")
        except Exception as e:
            print(f"❌ Error preparing transfer: {e}")

    async def twilio_audio_stream(self):
        """Handle incoming Twilio WebSocket audio stream."""
        while True:
            try:
                message = await websocket.receive()
                data = json.loads(message)
                event = data.get("event")

                if event == "start":
                    self.stream_sid = data["start"]["streamSid"]
                    self.call_sid = data["start"]["callSid"]
                    self.custom_params = data["start"]["customParameters"]
                    print(f"📡 Twilio stream started: {self.stream_sid}")
                    print(f"📞 Call SID: {self.call_sid}")
                    print(f"👤 Customer info: {self.custom_params}")
                    
                    active_calls[self.call_uuid] = self
                    await self.initialize_call()

                elif event == "media":
                    # Stop processing if transfer is requested
                    if self.transfer_requested:
                        continue
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

                    # Stop processing if transfer requested
                    if self.transfer_requested:
                        print("🔄 Transfer in progress, stopping Gemini responses")
                        break

                    if response.tool_call:
                        print("------ Function Called --------")
                        func_resps = []
                        for fc in response.tool_call.function_calls:
                            print(f"Function: {fc.name}")
                            
                            if fc.name == "request_human_transfer":
                                await self.request_transfer_to_admin()
                                # Return success response
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"status": "transfer_initiated", "message": "Transferring to representative"}
                                )
                            else:
                                resp = self._call_aldar_api(function_name=fc.name, parameters=fc.args)
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response=resp
                                )
                            func_resps.append(function_response)

                        await session.send_tool_response(function_responses=func_resps)

                    # Handle Gemini -> Twilio audio
                    if response.data:
                        pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                        self.merged_wav.writeframes(pcm_16k)

                        if self.stream_sid and not self.transfer_requested:
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

                # Only close websocket if not transferring
                if not self.transfer_requested:
                    await websocket.close(code=200)
                print(f"🏁 Call session {self.call_uuid} ended.")


# ============= ROUTES =============

@app.route('/call/token', methods=['GET'])
async def get_call_token():
    """Generate Twilio access token for customer calls"""
    identity = f"customer_{uuid4()}"
    
    access_token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        identity=identity
    )
    
    voice_grant = VoiceGrant(
        outgoing_application_sid=TWILIO_TWIML_APP_SID,
        incoming_allow=True
    )
    access_token.add_grant(voice_grant)
    
    return jsonify({
        'token': access_token.to_jwt(),
        'identity': identity
    })


@app.route('/admin/token', methods=['GET'])
async def get_admin_token():
    """Generate Twilio access token for admin"""
    identity = f"admin_{uuid4()}"
    
    access_token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        identity=identity
    )
    
    voice_grant = VoiceGrant(
        outgoing_application_sid=TWILIO_TWIML_APP_SID,
        incoming_allow=True
    )
    access_token.add_grant(voice_grant)
    
    return jsonify({
        'token': access_token.to_jwt(),
        'identity': identity
    })


@app.route('/admin/active-calls', methods=['GET'])
async def get_active_calls():
    """Get list of active calls"""
    calls_list = [
        {
            "call_uuid": uuid,
            "call_sid": bridge.call_sid,
            "customer_info": bridge.custom_params,
            "transfer_requested": bridge.transfer_requested,
            "duration": "active"
        }
        for uuid, bridge in active_calls.items()
    ]
    return jsonify({"calls": calls_list})


@app.route('/admin/request-transfer', methods=['POST'])
async def request_transfer():
    """Admin requests to take over a call"""
    data = await request.get_json()
    call_uuid = data.get('call_uuid')
    call_sid = data.get('call_sid')
    
    if call_uuid not in active_calls:
        return jsonify({"success": False, "error": "Call not found"}), 404
    
    bridge = active_calls[call_uuid]
    
    # Mark transfer as requested
    bridge.transfer_requested = True
    bridge.admin_stream_ready = True
    
    # Use Twilio API to redirect the call
    try:
        # Update the call to use admin TwiML
        twilio_client.calls(call_sid).update(
            twiml=f'''<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say>Please hold while we connect you to a representative.</Say>
                <Pause length="1"/>
                <Connect>
                    <Stream url="wss://al-dar-call.go-globe.dev/admin-stream/{call_uuid}">
                        <Parameter name="call_uuid" value="{call_uuid}" />
                        <Parameter name="admin_transfer" value="true" />
                    </Stream>
                </Connect>
            </Response>'''
        )
        
        print(f"✅ Call {call_sid} redirected to admin stream")
        
        return jsonify({
            "success": True,
            "call_uuid": call_uuid,
            "customer_info": bridge.custom_params
        })
    except Exception as e:
        print(f"❌ Error redirecting call: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin/call-status/<call_uuid>', methods=['GET'])
async def get_call_status(call_uuid):
    """Check if call is ready for admin to join"""
    if call_uuid not in active_calls:
        return jsonify({"status": "not_found"}), 404
    
    bridge = active_calls[call_uuid]
    
    if bridge.admin_stream_ready:
        return jsonify({"status": "ready_for_admin"})
    else:
        return jsonify({"status": "not_ready"})


@app.route('/voice', methods=['POST'])
async def voice():
    """TwiML endpoint for incoming/outgoing calls"""
    form = await request.form
    call_uuid = str(uuid4())
    
    # Get custom parameters
    name = form.get('name', 'Unknown')
    qid = form.get('qid', 'N/A')
    
    twiml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <Stream url="wss://al-dar-call.go-globe.dev/">
                <Parameter name="call_uuid" value="{call_uuid}" />
                <Parameter name="name" value="{name}" />
                <Parameter name="qid" value="{qid}" />
            </Stream>
        </Connect>
    </Response>'''
    
    return twiml_response, 200, {'Content-Type': 'text/xml'}


@app.route('/admin-voice', methods=['POST'])
async def admin_voice():
    """TwiML endpoint for admin calls"""
    form = await request.form
    call_uuid = form.get('call_uuid')
    admin_join = form.get('admin_join')
    
    if not call_uuid or call_uuid not in active_calls:
        return '''<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say>Call not found or has ended.</Say>
            <Hangup/>
        </Response>''', 200, {'Content-Type': 'text/xml'}
    
    bridge = active_calls[call_uuid]
    
    twiml_response = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect>
            <Stream url="wss://al-dar-call.go-globe.dev/admin-stream/{call_uuid}">
                <Parameter name="call_uuid" value="{call_uuid}" />
                <Parameter name="admin" value="true" />
            </Stream>
        </Connect>
    </Response>'''
    
    return twiml_response, 200, {'Content-Type': 'text/xml'}


# ============= WEBSOCKET ENDPOINTS =============

@app.websocket('/')
async def media_stream():
    """Main WebSocket endpoint for customer Twilio Media Stream (Gemini)"""
    print("🚀 Customer Twilio WebSocket connected.")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()


@app.websocket('/admin-stream/<call_uuid>')
async def admin_stream(call_uuid):
    """WebSocket endpoint for admin audio stream"""
    print(f"👔 Admin stream connected for call {call_uuid}")
    
    if call_uuid not in active_calls:
        print(f"❌ Call {call_uuid} not found")
        await websocket.close(1000)
        return
    
    bridge = active_calls[call_uuid]
    stream_sid = None
    
    try:
        while True:
            message = await websocket.receive()
            data = json.loads(message)
            event = data.get("event")
            
            if event == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"📡 Admin stream started: {stream_sid}")
                
                # Add transcription
                bridge.transcriptions.append({
                    "name": "system",
                    "transcription": "Admin connected to call"
                })
            
            elif event == "media":
                # Receive admin audio and record it
                audio_b64 = data["media"]["payload"]
                mulaw_bytes = base64.b64decode(audio_b64)
                pcm_bytes = audioop.ulaw2lin(mulaw_bytes, 2)
                pcm_16k, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                bridge.merged_wav.writeframes(pcm_16k)
            
            elif event == "stop":
                print("🛑 Admin stream stopped")
                bridge.transcriptions.append({
                    "name": "system",
                    "transcription": "Admin disconnected from call"
                })
                break
                
    except Exception as e:
        print(f"❌ Error in admin stream: {e}")
    finally:
        print(f"👔 Admin stream ended for {call_uuid}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3059)
