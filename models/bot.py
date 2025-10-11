import os
import pickle
from io import BytesIO
from dotenv import load_dotenv
from PIL import Image
from google import genai
from google.genai import types
import json
import wave


load_dotenv()


class Bot:
    def __init__(self, name, app):
        self.gm_key = app.config['SETTINGS']['apiKeys']['gemini']
        self.active_bot = None
        self.active_bot_name = app.config['SETTINGS'].get('model', 'gemini_2.0_flash')
        self.base_prompt = app.config["SETTINGS"]["prompt"]

        # Gemini model configurations
        self.google_models = {

            "gemini-2.5-flash": {
                "supports_images": True,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0.10, "output": 0.40}
            },
            "gemini-2.0-flash": {
                "supports_images": True,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0.10, "output": 0.40}
            },
        }

        self._set_bot(self.active_bot_name)

    @classmethod
    def get_bots(cls):
        return [
            ('Gemini 2.5 Flash', "gemini_2.0_flash"),
            ('Gemini 2.0 Flash', "gemini_2.0_flash"),
        ]
    def transcribe(self,audio_bytes):

        print(os.getenv('GEMINI_KEY'))
        client =  genai.Client(api_key=os.getenv('GEMINI_KEY'))

        response = client.models.generate_content(
          model='gemini-2.5-flash',
          contents=[
            'Transcribe this audio clip, only text no sounds ',
            types.Part.from_bytes(
              data=audio_bytes,
              mime_type='audio/mp3',
            )
          ]
        )
        return response.text

    def generate_audio(self,message):
        client =  genai.Client(api_key=os.getenv('GEMINI_KEY'))
        print(os.getenv('GEMINI_KEY'))

        response = client.models.generate_content(
           model="gemini-2.5-flash-preview-tts",
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

    def responed(self, input, id,type="text"):
        # if type == "audio":
        #     input = self._transcribe(input)
        print(input)
        chat_state = self._load_chat(id)
        response = chat_state["client"].chats.create(
            **chat_state["config"]
        ).send_message(input)

        tokens = self._count_tokens(response)
        self._save_chat(chat_state, id)
        return response.text, tokens

    def _get_google_model_name(self, bot_key):
        """Convert bot key back to actual model name"""
        return bot_key.replace("_", "-")

    def _set_bot(self, name):
        actual_model = self._get_google_model_name(name)
        if actual_model not in self.google_models:
            raise ValueError(f"Unsupported model: {name}")
        
        self.active_bot = genai.Client(api_key=self.gm_key)
        self.active_bot_name = name

    def create_chat(self, id, admin=None):
        """Create a new chat session with optional admin-specific settings"""
        print(admin)
        admin_settings = admin.settings if admin else {}
        text_content, images = self._process_files(admin.admin_id if admin else None)

        # Use admin-specific prompt if available, otherwise use base prompt
        prompt = admin_settings.get('prompt', self.base_prompt) if admin_settings else self.base_prompt

        # Initialize system prompt with language restrictions if specified
        languages = admin_settings.get('languages', ['English']) if admin_settings else ['English']
        self.sys_prompt = f"{prompt}\n\nOnly respond to user if the language is in the following, and respond in the user's language: {', '.join(languages)}"

        chat_state = self._init_google_chat(text_content, images)
        chat_state["model_name"] = self.active_bot_name
        chat_state["model_config"] = self._get_model_config()

        # Save chat state
        os.makedirs('./bin/chat/', exist_ok=True)
        with open(f'bin/chat/{id}.chatpl', 'wb') as file:
            pickle.dump(chat_state, file)

    def _get_model_config(self):
        return self._get_google_model_name(self.active_bot_name)

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
        actual_model = self._get_google_model_name(self.active_bot_name)
        model_config = self.google_models[actual_model]

        history = []

        # Only add images if the model supports them
        if model_config["supports_images"] and images:
            for img in images:
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                history.append(types.UserContent(
                    types.Part.from_bytes(
                        data=buffered.getvalue(), mime_type='image/jpeg')
                ))
        
        print(self.sys_prompt)
        return {
            "client": self.active_bot,
            "config": {
                "model": actual_model,
                "config": types.GenerateContentConfig(
                    system_instruction=f"{self.sys_prompt}\n{text_content}",
                    max_output_tokens=model_config["max_tokens"],
                    temperature=model_config["temperature"]
                ),
                "history": history
            }
        }

    def _load_chat(self, id):
        try:
            with open(f"bin/chat/{id}.chatpl", 'rb') as file:
                chat_state = pickle.load(file)
                # Set the active bot based on stored model
                if "model_name" in chat_state:
                    self._set_bot(chat_state["model_name"])
                else:
                    self._set_bot('gemini_2.0_flash')
                return chat_state
        except FileNotFoundError:
            raise ValueError(f"No chat session found for id {id}")

    def _save_chat(self, chat_state, id):
        # Ensure current model info is saved
        chat_state["model_name"] = self.active_bot_name
        chat_state["model_config"] = self._get_model_config()
        with open(f"bin/chat/{id}.chatpl", 'wb') as file:
            pickle.dump(chat_state, file)

    def _count_tokens(self, response):
        actual_model = self._get_google_model_name(self.active_bot_name)
        costs = self.google_models[actual_model]["pricing"]
        usage = response.usage_metadata.dict()
        
        input_tokens = usage['prompt_token_count']
        output_tokens = usage['candidates_token_count']

        input_cost = (input_tokens * costs["input"]) / 1000000
        output_cost = (output_tokens * costs["output"]) / 1000000

        return {
            "input": input_tokens,
            "output": output_tokens,
            "cost": (input_cost + output_cost) * 100,
            "bot": self.active_bot_name
        }


if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    app.config['SETTINGS'] = {
        'apiKeys': {
            'gemini': os.getenv('GEMINI_KEY')
        },
        'prompt': "You are a helpful AI assistant.",
        'model': 'gemini_2.0_flash'
    }

    bot = Bot('test', app)

    with open('sample.wav', 'rb') as f:
        audio_bytes = f.read()
    # print(bot._transcribe(audio_bytes).text)

    # Test bot
    for bot_name, bot_code in bot.get_bots():
        print(f"\nTesting {bot_name}...")
        bot._set_bot(bot_code)
        chat_id = f"test_{bot_code}"
        bot.create_chat(chat_id)
        response, tokens = bot.responed(audio_bytes, chat_id,type="audio")
        print(f"Response: {response[:100]}...")
        print(f"Tokens used: {tokens}")
