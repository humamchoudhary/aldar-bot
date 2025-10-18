import os
import pickle
import requests
from io import BytesIO
from dotenv import load_dotenv
from PIL import Image
from google import genai
from google.genai import types
import json


load_dotenv()


class Bot:
    def __init__(self, name, app):
        self.gm_key = app.config['SETTINGS']['apiKeys']['gemini']
        self.base_prompt = app.config["SETTINGS"]["prompt"]

        print(os.getenv('GEMINI_KEY'))
        self.client = genai.Client(api_key=os.getenv('GEMINI_KEY'))
        
        # Hardcoded model assignments
        self.transcription_model = "gemini-2.5-flash-lite"
        self.audio_generation_model = "gemini-2.5-flash-preview-tts"
        self.text_model = "gemini-2.5-flash"
        
        # Aldar Exchange API base URL
        self.aldar_base_url = "https://aldarexchangeuat.net/ONLINEApp"
        
        # Define Aldar Exchange tools
        self.tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="get_exchange_rate",
                        description="Get the current exchange rate for a specific rate type. Use type=1 for standard rates.",
                        parameters={
                            "type": "object",
                            "properties": {
                                "rate_type": {
                                    "type": "integer",
                                    "description": "The rate type code (e.g., 1 for standard rate)"
                                }
                            },
                            "required": ["rate_type"]
                        }
                    ),
                    types.FunctionDeclaration(
                        name="get_branch_details",
                        description="Get details of all Aldar Exchange branch locations including addresses, phone numbers, working hours, and coordinates.",
                        parameters={
                            "type": "object",
                            "properties": {}
                        }
                    ),
                    types.FunctionDeclaration(
                        name="calculate_exchange",
                        description="Calculate currency conversion between QAR and foreign currency. Specify either local currency amount (QAR) or foreign currency amount, not both.",
                        parameters={
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
                    )
                ]
            )
        ]

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
                return response.json()
            
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

    def transcribe(self, audio_bytes):
        """Transcribe audio to text"""
        response = self.client.models.generate_content(
            model=self.transcription_model,
            contents=[
                'Transcribe this audio clip accurately',
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type='audio/mp3',
                )
            ]
        )
        return response.text

    def generate_audio(self, message):
        """Generate audio from text"""
        response = self.client.models.generate_content(
            model=self.audio_generation_model,
            contents=f"Say: {message}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name='Achird',
                        )
                    )
                ),
            )
        )

        data = response.candidates[0].content.parts[0].inline_data.data
        return data

    def audio_to_text(self, audio_bytes):
        """Take audio and return text response"""
        # Transcribe audio to text
        transcribed_text = self.transcribe(audio_bytes)
        
        # Generate response using text model
        response = self.client.models.generate_content(
            model=self.text_model,
            contents=transcribed_text,
            config=types.GenerateContentConfig(
                tools=self.tools
            )
        )
        
        return response.text

    def audio_to_audio(self, audio_bytes):
        """Take audio and return both text and audio response"""
        # Transcribe audio to text
        transcribed_text = self.transcribe(audio_bytes)
        
        # Generate response using text model
        response = self.client.models.generate_content(
            model=self.text_model,
            contents=transcribed_text,
            config=types.GenerateContentConfig(
                tools=self.tools
            )
        )
        
        response_text = response.text
        
        # Generate audio from response text
        response_audio = self.generate_audio(response_text)
        
        return response_text, response_audio

    def respond(self, input, id, type="text"):
        """Main response method - handles text, audio input with function calling"""
        if type == "audio":
            # If input is audio, transcribe it first
            input = self.transcribe(input)
        
        print(f"User input: {input}")
        chat_state = self._load_chat(id)
        
        # Send initial message with tools enabled
        response = chat_state["chat"].send_message(input)
        
        # Handle function calls
        while response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            
            # Check if there's a function call
            if hasattr(part, 'function_call') and part.function_call:
                function_call = part.function_call
                function_name = function_call.name
                function_args = dict(function_call.args)
                
                print(f"Function called: {function_name}")
                print(f"Arguments: {function_args}")
                
                # Execute the function
                function_response = self._call_aldar_api(function_name, function_args)
                print(f"Function response: {function_response}")
                
                # Send function response back to model
                response = chat_state["chat"].send_message(
                    types.Part.from_function_response(
                        name=function_name,
                        response=function_response
                    )
                )
            else:
                # No more function calls, break the loop
                break

        tokens = self._count_tokens(response)
        self._save_chat(chat_state, id)
        return response.text, tokens

    def create_chat(self, id, admin=None):
        """Create a new chat session with optional admin-specific settings"""
        print(admin)
        admin_settings = admin.settings if admin else {}
        text_content, images = self._process_files(admin.admin_id if admin else None)

        # Use admin-specific prompt if available, otherwise use base prompt
        prompt = admin_settings.get('prompt', self.base_prompt) if admin_settings else self.base_prompt

        # Initialize system prompt with language restrictions if specified
        languages = admin_settings.get('languages', ['English']) if admin_settings else ['English']
        self.sys_prompt = f"{prompt}\n\nYou have access to Aldar Exchange APIs to help users with currency exchange rates, branch information, and conversion calculations. Use these tools when users ask about exchange rates, currency conversion, or branch locations."

        chat_state = self._init_google_chat(text_content, images)

        # Save chat state
        os.makedirs('./bin/chat/', exist_ok=True)
        with open(f'bin/chat/{id}.chatpl', 'wb') as file:
            pickle.dump(chat_state, file)

    def _process_files(self, admin_id):
        text_content = []
        images = []
        
        if not admin_id:
            return "", []
            
        base_path = os.path.join(os.getcwd(), 'user_data', str(admin_id))

        # Check if files directory exists
        files_dir = os.path.join(base_path, "files")
        if not os.path.exists(files_dir):
            return "", []

        # Process files in files directory
        for file_name in os.listdir(files_dir):
            file_path = os.path.join(files_dir, file_name)
            file_ext = os.path.splitext(file_name)[1].lower()

            try:
                if file_ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                    with Image.open(file_path) as img:
                        images.append(img.copy())
                elif file_ext == '.txt':
                    url = file_name.replace("*", "/").replace(".txt", "")
                    with open(file_path, 'r', encoding='utf-8') as f:
                        text_content.extend([
                            f"<url>{url}</url>",
                            f"<file url='{url}'>{f.read()}</file>"
                        ])
            except Exception as e:
                print(f"Error processing {file_name}: {str(e)}")

        # Process files in db directory
        db_dir = os.path.join(base_path, "db")
        if os.path.exists(db_dir):
            for file_name in os.listdir(db_dir):
                file_path = os.path.join(db_dir, file_name)
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f).get('data', [])
                    string_re = "\n".join(
                        f"{k} : {v}"
                        for d in data
                        for k, v in d.items()
                    )
                    if string_re:
                        text_content.append(string_re)
                except Exception as e:
                    print(f"Error processing DB file {file_name}: {str(e)}")
        
        print(text_content)
        return "\n".join(text_content), images

    def _init_google_chat(self, text_content, images):
        """Initialize Google chat session with function calling"""
        history = []

        # Add images to history if any
        if images:
            for img in images:
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                history.append(types.Content(
                    role="user",
                    parts=[types.Part.from_bytes(
                        data=buffered.getvalue(), mime_type='image/jpeg')]
                ))
        
        print(self.sys_prompt)
        
        # Create chat with tools enabled
        chat = self.client.chats.create(
            model=self.text_model,
            config=types.GenerateContentConfig(
                system_instruction=f"{self.sys_prompt}\n{text_content}",
                max_output_tokens=8192,
                temperature=0.7,
                tools=self.tools
            ),
            history=history
        )
        
        return {
            "client": self.client,
            "chat": chat,
            "config": {
                "model": self.text_model,
                "config": types.GenerateContentConfig(
                    system_instruction=f"{self.sys_prompt}\n{text_content}",
                    max_output_tokens=8192,
                    temperature=0.7,
                    tools=self.tools
                ),
                "history": history
            }
        }

    def _load_chat(self, id):
        try:
            with open(f"bin/chat/{id}.chatpl", 'rb') as file:
                chat_state = pickle.load(file)
                return chat_state
        except FileNotFoundError:
            raise ValueError(f"No chat session found for id {id}")

    def _save_chat(self, chat_state, id):
        with open(f"bin/chat/{id}.chatpl", 'wb') as file:
            pickle.dump(chat_state, file)

    def _count_tokens(self, response):
        """Calculate token usage and costs"""
        # Default pricing
        costs = {"input": 0.10, "output": 0.40}
        usage = response.usage_metadata.dict()
        
        input_tokens = usage['prompt_token_count']
        output_tokens = usage['candidates_token_count']

        input_cost = (input_tokens * costs["input"]) / 1000000
        output_cost = (output_tokens * costs["output"]) / 1000000

        return {
            "input": input_tokens,
            "output": output_tokens,
            "cost": (input_cost + output_cost) * 100,
            "bot": self.text_model
        }


if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    app.config['SETTINGS'] = {
        'apiKeys': {
            'gemini': os.getenv('GEMINI_KEY')
        },
        'prompt': "You are a helpful AI assistant specialized in helping users with currency exchange information.",
        'model': 'gemini-2.5-flash'
    }

    bot = Bot('test', app)

    # Test the function calling
    print("\nTesting function calling with chat...")
    chat_id = "test_chat_tools"
    bot.create_chat(chat_id)
    
    # Test 1: Get branch details
    print("\n=== Test 1: Get branch details ===")
    response, tokens = bot.respond("Show me all Aldar Exchange branches", chat_id, type="text")
    print(f"Response: {response}")
    print(f"Tokens used: {tokens}")
    
    # Test 2: Calculate exchange
    print("\n=== Test 2: Calculate exchange ===")
    response, tokens = bot.respond("How much QAR would I need to buy 1000 USD?", chat_id, type="text")
    print(f"Response: {response}")
    print(f"Tokens used: {tokens}")
    
    # Test 3: Get exchange rate
    print("\n=== Test 3: Get exchange rate ===")
    response, tokens = bot.respond("What's the current exchange rate?", chat_id, type="text")
    print(f"Response: {response}")
    print(f"Tokens used: {tokens}")
