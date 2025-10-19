from uuid import uuid4
from twilio.twiml.voice_response import VoiceResponse
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
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
LOG_ENDPOINT = os.getenv("LOG_ENDPOINT", "https://192.168.100.4:5000/log")
SYS_INST_ENDPOINT = os.getenv("SYS_INST_ENDPOINT", "https://192.168.100.4:5000/call/get-files")

app = Quart(__name__)

# Global vars
call_transcriptions = []
call_filename = None




class GeminiTwilioBridge:
    def __init__(self):
        self.client = genai.Client(api_key=os.getenv("GEMINI_KEY"))
        self.model_id = "gemini-2.5-flash-native-audio-latest"
        self.system_instruction = f"""

                    You are a professional AI assistant trained in customer service and sales communication.

                    Your role is to provide clear, helpful, and concise answers (1–3 lines max) based strictly on the uploaded file titled “Omnichannel Customer Experience Solutions – Service Profile.” Do not use external sources.
                    📌 Key Guidelines

                    1. Stay Within the Document Scope

                        Only use info from the uploaded file.

                        If a request goes beyond the file, reply:
                        “I can only answer questions based on the provided company profile.”

                    2. Clear Responses Based on Common Requests

                        CEO Message → Share the CEO’s note from the document.

                        Contact Info → Provide email, phone, or any listed contact method.

                        Services → Brief summary of the services offered.

                        Use Cases → Mention 1–2 industries or example use cases.

                        Technology → List any highlighted technologies or integrations.

                    3. Answer Style

                        Short and focused — no long explanations or fluff.

                        Reference links using this format:
                        Example: www.aldar.com*info.php.txt → 👉 aldar's website info page

                    💬 If Question is Vague or Out of Scope


                    💡 Encourage Detail for Better Help

                        “To assist you better, please share what you're looking for. The more we know, the faster we can help.”

                    💸 Talking About Pricing or Investment

                        Do not provide prices unless asked directly.

                        Instead, say:

                        “Every project is an investment, usually spread over 4–5 years. May I ask what investment range or available funds you’re working with?”

                     
                    Always respond in short answers no need for long answers just to the point        \n\n"""

        self.get_system_instruction()

        self.config = {
            "response_modalities": ["AUDIO"],
            "thinking_config": {"thinking_budget": 0},
            "output_audio_transcription": {},
            "input_audio_transcription": {},
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

        self.stream_sid = None

        global call_filename
        call_filename = f"call_{uuid4()}.wav"
        call_filename = os.path.join("recordings",call_filename)

        # Prepare WAV files
        self.merged_wav = wave.open(call_filename, "wb")
        self.merged_wav.setnchannels(1)
        self.merged_wav.setsampwidth(2)
        self.merged_wav.setframerate(16000)

        # Aldar Exchange API base URL
        self.aldar_base_url = "https://aldarexchangeuat.net/ONLINEApp"
        
        print(f"📁 Created file for this call: {call_filename}")

    def get_system_instruction(self):
        resp = requests.get(SYS_INST_ENDPOINT,verify=False)
        if resp.status_code==200:

            self.system_instruction += f"Additional Data:\n{resp.text}"
            print(self.system_instruction)
        else:
            raise BrokenPipeError("Couldnot get system instruction")

    async def twilio_audio_stream(self):
        """
        Handle incoming Twilio websocket audio stream.
        Converts µ-law to PCM and yields PCM for Gemini.
        """
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

                    # Write to merged WAV (8kHz → upsampled to 16kHz)
                    pcm_16k, _ = audioop.ratecv(pcm_bytes, 2, 1, 8000, 16000, None)
                    self.merged_wav.writeframes(pcm_16k)
                    yield pcm_16k

                elif event == "stop":
                    print("🛑 Twilio stream stopped")
                    break

            except Exception as e:
                print(f"❌ Error in twilio_audio_stream: {e}")
                break

    def convert_audio_to_twilio_format(self, audio_data: bytes) -> str:
        """
        Converts Gemini PCM (24kHz) → 8kHz mulaw → base64 for Twilio.
        """
        pcm_8k, _ = audioop.ratecv(audio_data, 2, 1, 24000, 8000, None)
        mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
        return base64.b64encode(mulaw_data).decode("utf-8")

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
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API call failed: {str(e)}"}

    async def gemini_session(self):
        """
        Bridges audio stream between Twilio and Gemini.
        """
        global call_transcriptions
        print("✅ Connected to Gemini session")

        async with self.client.aio.live.connect(model=self.model_id, config=self.config) as session:
            try:
                bot_buffer = ""  # buffer to accumulate Gemini's partial outputs

                async for response in session.start_stream(
                    stream=self.twilio_audio_stream(),
                    mime_type="audio/pcm;rate=16000"
                ):

                    if response.tool_call:
                        print("------ Function Called --------")
                        func_resps = []
                        print(response.tool_call)
                        for fc in response.tool_call.function_calls:
                            # print(fc)
                            resp = self._call_aldar_api(function_name=fc.name,parameters=fc.args)
                            function_response = types.FunctionResponse(
                                id=fc.id,
                                name=fc.name,
                                response=resp # simple, hard-coded function response
                            )
                            func_resps.append(function_response)

                        await session.send_tool_response(function_responses=func_resps)

                    if response.data:
                        # Write Gemini audio output into same WAV file
                        pcm_16k, _ = audioop.ratecv(response.data, 2, 1, 24000, 16000, None)
                        self.merged_wav.writeframes(pcm_16k)

                        # Send back to Twilio
                        b64_audio = self.convert_audio_to_twilio_format(response.data)
                        if self.stream_sid:
                            await websocket.send(json.dumps({
                                "event": "media",
                                "streamSid": self.stream_sid,
                                "media": {"payload": b64_audio}
                            }))
                            print("🎧 Sent Gemini audio chunk to Twilio")
                        else:
                            print("⚠️ No streamSid yet")

                    # --- transcription handling ---
                    if response.server_content.input_transcription:
                        user_text = response.server_content.input_transcription.text
                        print("👤 User Transcript:", user_text)
                        call_transcriptions.append({
                            "name": "user",
                            "transcription": user_text
                        })

                        # If bot was mid-sentence, flush its buffer
                        if bot_buffer.strip():
                            call_transcriptions.append({
                                "name": "bot",
                                "transcription": bot_buffer.strip()
                            })
                            bot_buffer = ""  # reset

                    if response.server_content.output_transcription:
                        chunk = response.server_content.output_transcription.text
                        print("🤖 Bot Transcript Chunk:", chunk)
                        bot_buffer += " " + chunk.strip()

                    # If Gemini signals end of model turn → flush accumulated bot message
                    if response.server_content.model_turn:
                        if bot_buffer.strip():
                            call_transcriptions.append({
                                "name": "bot",
                                "transcription": bot_buffer.strip()
                            })
                            print("🤖 Bot Message Complete:", bot_buffer.strip())
                            bot_buffer = ""
                    # --------------------------------

            except Exception as e:
                print(f"❌ Error in gemini_session: {e}")

            finally:
                # flush any leftover bot transcript when session ends
                if bot_buffer.strip():
                    call_transcriptions.append({
                        "name": "bot",
                        "transcription": bot_buffer.strip()
                    })

                print("💾 Closing WAV file and session")
                self.merged_wav.close()
                await websocket.close(code=200)
                await session.close()

                # Send POST log after call ends
                await self.send_call_log()

    async def send_call_log(self):
        """
        Sends transcription + file name to endpoint after call.
        """
        try:
            payload = {
                "file_name": call_filename,
                "transcription": call_transcriptions
            }

            print(f"📤 Sending call log to {LOG_ENDPOINT}")
            # print(payload)
            # async with aiohttp.ClientSession() as session:
                # async with session.post(LOG_ENDPOINT, json=payload) as resp:
                #     if resp.status == 200:
                #         print("✅ Call log successfully sent!")
                #     else:
                #         print(f"⚠️ Call log send failed: {resp.status}")
        except Exception as e:
            print(f"❌ Error sending call log: {e}")

@app.websocket('/')
async def media_stream():
    """
    Quart WebSocket endpoint for Twilio Media Stream.
    """
    print("🚀 Twilio WebSocket connected")
    bridge = GeminiTwilioBridge()
    await bridge.gemini_session()
    print("🏁 Gemini session ended")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5049)
