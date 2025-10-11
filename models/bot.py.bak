import os
import pickle
import base64
from io import BytesIO
# from p# # print import p# print
from dotenv import load_dotenv
from PIL import Image
import anthropic
import openai
import requests
from google import genai
from google.genai import types
import json
import pdfplumber
load_dotenv()


class DeepseekClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1/chat/completions"

    def chat(self, messages, temperature=0.7):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature
        }
        response = requests.post(self.base_url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()


class Bot:
    def __init__(self, name, app):
        self.gm_key = app.config['SETTINGS']['apiKeys']['gemini']
        self.gpt_key = app.config['SETTINGS']['apiKeys']['openAi']
        self.cld_key = app.config['SETTINGS']['apiKeys']['claude']
        self.dp_key = app.config['SETTINGS']['apiKeys']['deepseek']

        self.active_bot = None
        # self.active_bot_name = ""

        self.active_bot_name = app.config['SETTINGS'].get(
            'model', 'gemini_2.0_flash')

        self.base_prompt = app.config["SETTINGS"]["prompt"]

        # Enhanced Google model configurations
        self.google_models = {
            "gemini-2.0-flash": {
                "supports_images": True,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0.10, "output": 0.40}
            },
            "gemini-1.5-pro": {
                "supports_images": True,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 3.50, "output": 10.50}
            },
            "gemini-1.5-flash": {
                "supports_images": True,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0.075, "output": 0.30}
            },
            "gemini-1.0-pro": {
                "supports_images": False,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0.50, "output": 1.50}
            },
            "gemma-3-27b-it": {
                "supports_images": False,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0, "output": 0}
            },
            "gemma-3-12b-it": {
                "supports_images": False,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0, "output": 0}
            },
            "gemma-3-1b-it": {
                "supports_images": False,
                "max_tokens": 8192,
                "temperature": 0.7,
                "pricing": {"input": 0, "output": 0}
            }
        }

        self.bot_maps = {
            "claude-3": self._claude,
            "gpt-4": self._gpt,
            "dp-chat": self._deepseek
        }

        # Add Google models to bot_maps dynamically
        for model_name in self.google_models.keys():
            bot_key = model_name.replace("-", "_")
            self.bot_maps[bot_key] = self._google_model

        self._set_bot(self.active_bot_name)

    @classmethod
    def get_bots(cls):
        # Static method to get available bots - you may want to make this dynamic too
        google_models = [
            ('Gemini 2.0 Flash', "gemini_2.0_flash"),
            ('Gemini 1.5 Pro', "gemini_1.5_pro"),
            ('Gemini 1.5 Flash', "gemini_1.5_flash"),
            ('Gemini 1.0 Pro', "gemini_1.0_pro"),
            ('Gemma 3 27B', "gemma_3_27b_it"),
            ('Gemma 3 12B', "gemma_3_12b_it"),
            ('Gemma 3 1B', "gemma_3_1b_it")
        ]

        other_models = [
            ('Claude 3', 'claude-3'),
            ('GPT-4', 'gpt-4'),
            ('Deepseek', 'dp-chat')
        ]

        return google_models + other_models

    def responed(self, input, id):
        chat_state = self._load_chat(id)
        # p# print(self.bot_maps)
        # # print(self.active_bot_name)
        if self.active_bot_name not in self.bot_maps:
            raise ValueError(f"Unsupported bot: {self.active_bot_name}")
        return self.bot_maps[self.active_bot_name](input, id)

    def _get_google_model_name(self, bot_key):
        """Convert bot key back to actual model name"""
        return bot_key.replace("_", "-")

    def _is_google_model(self, model_name):
        """Check if the model is a Google model"""

        # # # print(f"Bot Name: {model_name}")
        actual_model = self._get_google_model_name(model_name)

        # # # print(f"Bot Name: {actual_model}")
        # # # print(self.google_models)
        return actual_model in self.google_models

    def _set_bot(self, name):
        # # print(f"Bot Name: {name}")
        if self._is_google_model(name):
            self.active_bot = genai.Client(api_key=self.gm_key)
            self.active_bot_name = name
        elif name == "claude-3":
            self.active_bot = anthropic.Client(api_key=self.cld_key)
            self.active_bot_name = name
        elif name == "gpt-4":
            openai.api_key = self.gpt_key
            self.active_bot_name = name
        elif name == "dp-chat":
            self.active_bot = DeepseekClient(api_key=self.dp_key)
            self.active_bot_name = name
        else:
            raise NotImplementedError(f'Bot not implemented: {name}')

    # def create_chat(self, id, admin):
    #     text_content, images = self._process_files()
    #
    #     if not os.path.exists('./bin/chat/'):
    #         os.makedirs('./bin/chat/')
    #
    #     if self._is_google_model(self.active_bot_name):
    #         chat_state = self._init_google_chat(text_content, images)
    #     else:
    #         init_method = getattr(
    #             self, f'_init_{self.active_bot_name.replace("-", "_")}_chat')
    #         chat_state = init_method(text_content, images)
    #
    #     # Store the model name in the chat state
    #     chat_state["model_name"] = self.active_bot_name
    #     chat_state["model_config"] = self._get_model_config()
    #
    #     with open(f'bin/chat/{id}.chatpl', 'wb') as file:
    #         pickle.dump(chat_state, file)

    def create_chat(self, id, admin=None):
        """Create a new chat session with optional admin-specific settings"""
        print(admin)
        admin_settings = admin.settings
        text_content, images = self._process_files(admin.admin_id)

        # Use admin-specific prompt if available, otherwise use base prompt
        prompt = admin_settings.get(
            'prompt', self.base_prompt) if admin_settings else self.base_prompt

        # Initialize system prompt with language restrictions if specified
        languages = admin_settings.get(
            'languages', ['English']) if admin_settings else ['English']
        self.sys_prompt = f"{prompt}\n\nOnly respond to user if the langauge is in the following, and responsed in the users langauge: {
            ', '.join(languages)}"

        if self._is_google_model(self.active_bot_name):
            chat_state = self._init_google_chat(text_content, images)
        else:
            init_method = getattr(
                self, f'_init_{self.active_bot_name.replace("-", "_")}_chat')
            chat_state = init_method(text_content, images)

        chat_state["model_name"] = self.active_bot_name
        chat_state["model_config"] = self._get_model_config()

        # Save chat state
        os.makedirs('./bin/chat/', exist_ok=True)
        with open(f'bin/chat/{id}.chatpl', 'wb') as file:
            pickle.dump(chat_state, file)

    def _get_model_config(self):
        if self._is_google_model(self.active_bot_name):
            return self._get_google_model_name(self.active_bot_name)

        return {
            "claude-3": "claude-3-opus-20240229",
            "gpt-4": "gpt-4-vision-preview",
            "dp-chat": "deepseek-chat"
        }.get(self.active_bot_name, "unknown")

    def _process_files(self, admin_id):
        text_content = []
        images = []
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

    # Universal Google model initializer
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

    # Keep existing initializers for other models
    def _init_claude_3_chat(self, text_content, images):
        messages = [{
            "role": "system",
            "content": f"{self.sys_prompt}\n{text_content}"
        }]

        for img in images:
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.b64encode(buffered.getvalue()).decode('utf-8')
                        }
                    }
                ]
            })

        return {
            "client": self.active_bot,
            "config": {
                "model": "claude-3-opus-20240229",
                "max_tokens": 1000,
                "temperature": 0.7,
                "history": messages
            }
        }

    def _init_gpt_4_chat(self, text_content, images):
        messages = [{
            "role": "system",
            "content": f"{self.sys_prompt}\n{text_content}"
        }]

        for img in images:
            buffered = BytesIO()
            img.save(buffered, format="JPEG")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": "Attached image:"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
                        }
                    }
                ]
            })

        return {
            "client": openai.ChatCompletion,
            "config": {
                "model": "gpt-4-vision-preview",
                "history": messages
            }
        }

    def _init_dp_chat_chat(self, text_content, images):
        return {
            "client": self.active_bot,
            "config": {
                "model": "deepseek-chat",
                "messages": [{
                    "role": "system",
                    "content": f"{self.sys_prompt}\n{text_content}"
                }],
                "temperature": 0.7
            }
        }

    # Universal Google model response handler
    def _google_model(self, input, id):
        chat_state = self._load_chat(id)
        print(chat_state)
        response = chat_state["client"].chats.create(
            **chat_state["config"]
        ).send_message(input)

        tokens = self._count_tokens(response)
        print(tokens)
        self._save_chat(chat_state, id)
        return response.text, tokens

    # Keep existing response handlers for other models
    def _claude(self, input, id):
        chat_state = self._load_chat(id)
        chat_state["config"]["messages"].append(
            {"role": "user", "content": input})

        response = chat_state["client"].messages.create(
            **chat_state["config"]
        )

        tokens = self._count_tokens(response)
        chat_state["config"]["messages"].append({
            "role": "assistant",
            "content": response.content[0].text
        })
        self._save_chat(chat_state, id)
        return response.content[0].text, tokens

    def _gpt(self, input, id):
        chat_state = self._load_chat(id)
        chat_state["config"]["messages"].append(
            {"role": "user", "content": input})

        response = chat_state["client"].create(
            **chat_state["config"]
        )

        tokens = self._count_tokens(response)
        chat_state["config"]["messages"].append({
            "role": "assistant",
            "content": response.choices[0].message.content
        })
        self._save_chat(chat_state, id)
        return response.choices[0].message.content, tokens

    def _deepseek(self, input, id):
        chat_state = self._load_chat(id)

        if "messages" not in chat_state["config"]:
            chat_state["config"]["messages"] = []

        chat_state["config"]["messages"].append({
            "role": "user",
            "content": input
        })

        try:
            response = chat_state["client"].chat(
                messages=chat_state["config"]["messages"],
                temperature=chat_state["config"].get("temperature", 0.7)
            )

            if not isinstance(response, dict) or "choices" not in response:
                raise ValueError("Invalid response format from Deepseek API")

            assistant_message = response["choices"][0]["message"]["content"]

            chat_state["config"]["messages"].append({
                "role": "assistant",
                "content": assistant_message
            })

            tokens = self._count_tokens(response)
            self._save_chat(chat_state, id)
            return assistant_message, tokens

        except Exception as e:
            # # print(f"Deepseek API error: {str(e)}")
            chat_state["config"]["messages"].pop()
            raise

    def _load_chat(self, id):
        try:
            with open(f"bin/chat/{id}.chatpl", 'rb') as file:
                chat_state = pickle.load(file)
                # Set the active bot based on stored model
                if "model_name" in chat_state:
                    self._set_bot(chat_state["model_name"])
                else:
                    self._set_bot('gemini_2_0_flash')  # Updated default
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
        # Enhanced pricing with Google models
        pricing = {
            "claude-3": {"input": 15, "output": 75},
            "gpt-4": {"input": 0.03, "output": 0.06},
            "dp-chat": {"input": 0.27, "output": 1.10}
        }

        bot_name = self.active_bot_name

        # Handle Google models
        if self._is_google_model(bot_name):
            actual_model = self._get_google_model_name(bot_name)
            costs = self.google_models[actual_model]["pricing"]
            usage = response.usage_metadata.dict()
            input_tokens = usage['prompt_token_count']
            output_tokens = usage['candidates_token_count']
        else:
            costs = pricing.get(bot_name, {"input": 0, "output": 0})
            if bot_name == "claude-3":
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
            elif bot_name == "gpt-4":
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
            elif bot_name == "dp-chat":
                input_tokens = response["usage"]["prompt_tokens"]
                output_tokens = response["usage"]["completion_tokens"]
            else:
                input_tokens = output_tokens = 0

        input_cost = (input_tokens * costs["input"]) / 1000000
        output_cost = (output_tokens * costs["output"]) / 1000000

        return {
            "input": input_tokens,
            "output": output_tokens,
            "cost": (input_cost + output_cost)*100,
            "bot": bot_name
        }


if __name__ == "__main__":
    from flask import Flask
    app = Flask(__name__)
    app.config['SETTINGS'] = {
        'apiKeys': {
            'gemini': os.getenv('GEMINI_API_KEY'),
            'openAi': os.getenv('OPENAI_API_KEY'),
            'claude': os.getenv('CLAUDE_API_KEY'),
            'deepseek': os.getenv('DEEPSEEK_API_KEY')
        },
        'prompt': "You are a helpful AI assistant.",
        'model': 'gm_2_0_f'
    }

    bot = Bot('test', app)

    # Test each bot
    for bot_name, bot_code in bot.get_bots():
        # # print(f"\nTesting {bot_name}...")
        bot._set_bot(bot_code)
        chat_id = f"test_{bot_code}"
        bot.create_chat(chat_id)
        response, tokens = bot.responed("Hello! What can you do?", chat_id)
        # # print(f"Response: {response[:100]}...")
        # # print(f"Tokens used: {tokens}")
