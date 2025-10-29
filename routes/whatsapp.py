from flask import Flask, current_app, request, jsonify, g
import requests
import os
from io import BytesIO
from pydub import AudioSegment

from services.admin_service import AdminService
from services.chat_service import ChatService
from services.whatsapp_service import WhatsappService
from . import wa_bp

WHATSAPP_TOKEN = os.getenv('WHATSAPP_TOKEN')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN', 'your_verify_token_here')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID')
VERSION = 'v24.0'
DEFAULT_ADMIN_ID = os.getenv("DEFAULT_ADMIN_ID")


@wa_bp.route('/webhook', methods=['GET'])
def verify_webhook():
    """Verify webhook for WhatsApp Business API"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        return challenge, 200
    else:
        return "Forbidden", 403


@wa_bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming WhatsApp messages - returns 200 immediately"""
    try:
        data = request.get_json()
        
        # Store data in g for after_request processing
        g.webhook_data = data
        
        # Return 200 immediately
        return "Success", 200
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"{e}", 500


@wa_bp.after_request
def process_webhook_after_response(response):
    """Process webhook data after sending response"""
    # Only process if we have webhook data stored
#     if hasattr(g, 'webhook_data'):
    data = g.webhook_data
#         
#         # Process in a separate thread to avoid blocking
#         from threading import Thread
#         thread = Thread(target=process_webhook_data, args=(data,))
#         thread.daemon = True
#         thread.start()
#     
#     return response
#
#
# def process_webhook_data(data):
    # """Process webhook data asynchronously"""
    try:
        from flask import current_app
        
        with current_app.app_context():
            wa_service = WhatsappService(current_app.db)
            
            # Check if this is a message event
            if data.get('object') == 'whatsapp_business_account':
                entries = data.get('entry', [])
                
                for entry in entries:
                    changes = entry.get('changes', [])
                    
                    for change in changes:
                        value = change.get('value', {})
                        
                        # Check if there are messages
                        if 'messages' in value:
                            messages = value['messages']
                            
                            for message in messages:
                                # Get message details
                                from_number = message.get('from')
                                chat = wa_service.get_by_phone_no(from_number)
                                admin = AdminService(current_app.db).get_admin_by_id(DEFAULT_ADMIN_ID)
                                if not chat:
                                    current_app.bot.create_chat(from_number, admin)
                                
                                if not chat:
                                    wa_service.create(from_number)
                                
                                message_type = message.get('type')
                                
                                # Handle text messages
                                if message_type == 'text':
                                    user_message = message.get('text', {}).get('body', '')
                                    wa_service.add_message(user_message, from_number, from_number, type="text")
                                    
                                    msg, usage = current_app.bot.respond(user_message, from_number)
                                    wa_service.add_message(msg, from_number, "bot", type="text")
                                    send_whatsapp_message(from_number, msg)
                                
                                # Handle audio messages
                                elif message_type == 'audio':
                                    audio_data = message.get('audio', {})
                                    audio_id = audio_data.get('id')
                                    audio_mime_type = audio_data.get('mime_type', 'audio/ogg')
                                    
                                    # Download audio from WhatsApp
                                    audio_bytes = download_whatsapp_media(audio_id)
                                    
                                    if audio_bytes:
                                        # Transcribe audio to text
                                        transcribed_text = current_app.bot.transcribe(audio_bytes)
                                        
                                        # Save user audio message
                                        message_id = wa_service.add_message(transcribed_text, from_number, from_number, type="audio")
                                        
                                        # Save audio file
                                        save_path = os.path.join('files', f"{from_number}", f"{message_id}.ogg")
                                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                                        
                                        with open(save_path, 'wb') as f:
                                            f.write(audio_bytes)
                                        
                                        # Get bot response
                                        msg, usage = current_app.bot.respond(transcribed_text, from_number)
                                        
                                        # Generate audio response
                                        audio_response = current_app.bot.generate_audio(msg)
                                        
                                        # Convert to OGG Opus format for WhatsApp
                                        ogg_audio = convert_to_ogg_opus(audio_response)
                                        
                                        if ogg_audio:
                                            # Save bot audio message
                                            bot_message_id = wa_service.add_message(msg, from_number, "bot", type="audio")
                                            bot_audio_path = os.path.join('files', f"{from_number}", f"{bot_message_id}.ogg")
                                            
                                            # Save bot audio file
                                            with open(bot_audio_path, 'wb') as f:
                                                f.write(ogg_audio)
                                            
                                            # Send audio response to user
                                            send_whatsapp_audio(from_number, ogg_audio)
                                        else:
                                            send_whatsapp_message(from_number, msg)  # Fall back to text
                                    else:
                                        send_whatsapp_message(from_number, "Sorry, I couldn't process your audio message.")
                                
                                # Mark message as read
                                message_id = message.get('id')
                                mark_message_read(message_id)
    
    except Exception as e:
        import traceback
        traceback.print_exc()


def detect_audio_format(audio_data):
    """Detect audio format from file signature (magic bytes)"""
    if len(audio_data) < 12:
        return None
    
    # Check common audio format signatures
    if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
        return 'wav'
    elif audio_data[:4] == b'OggS':
        return 'ogg'
    elif audio_data[:3] == b'ID3' or audio_data[:2] == b'\xff\xfb' or audio_data[:2] == b'\xff\xf3':
        return 'mp3'
    elif audio_data[:4] == b'fLaC':
        return 'flac'
    elif audio_data[:4] == b'ftyp' or audio_data[4:8] == b'ftyp':
        return 'mp4'
    
    return None


def convert_to_ogg_opus(audio_data):
    """Convert audio data to OGG Opus format for WhatsApp"""
    try:
        # Detect the audio format
        detected_format = detect_audio_format(audio_data)
        
        audio_buffer = BytesIO(audio_data)
        
        # Try to load audio without specifying format first (let pydub detect)
        try:
            if detected_format:
                audio = AudioSegment.from_file(audio_buffer, format=detected_format)
            else:
                # Try common formats
                audio = None
                for fmt in ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac']:
                    try:
                        audio_buffer.seek(0)
                        audio = AudioSegment.from_file(audio_buffer, format=fmt)
                        break
                    except:
                        continue
                
                if audio is None:
                    raise ValueError("Could not detect audio format")
        except Exception as e:
            # Try loading raw PCM data (common for some TTS APIs)
            try:
                audio_buffer.seek(0)
                audio = AudioSegment(
                    data=audio_data,
                    sample_width=2,  # 16-bit
                    frame_rate=24000,  # Common TTS sample rate
                    channels=1
                )
            except:
                raise
        
        # Convert to mono if stereo
        if audio.channels > 1:
            audio = audio.set_channels(1)
        
        # Set to 16kHz sample rate (WhatsApp recommendation)
        audio = audio.set_frame_rate(16000)
        
        # Export as OGG with Opus codec
        output_buffer = BytesIO()
        audio.export(
            output_buffer,
            format='ogg',
            codec='libopus',
            parameters=["-strict", "-2"]
        )
        
        output_buffer.seek(0)
        return output_buffer.read()
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None


def download_whatsapp_media(media_id):
    """Download media file from WhatsApp"""
    try:
        # Step 1: Get media URL
        url = f"https://graph.facebook.com/{VERSION}/{media_id}"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}"
        }
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        media_url = response.json().get('url')
        
        if not media_url:
            return None
        
        # Step 2: Download the actual media file
        media_response = requests.get(media_url, headers=headers)
        media_response.raise_for_status()
        
        return media_response.content
    
    except requests.exceptions.RequestException as e:
        import traceback
        traceback.print_exc()
        return None


def send_whatsapp_audio(phone_number, audio_data):
    """Send audio message via WhatsApp"""
    try:
        # Step 1: Upload audio to WhatsApp
        upload_url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/media"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}"
        }
        
        # Create a file-like object from audio bytes
        audio_file = BytesIO(audio_data)
        
        files = {
            'file': ('audio.ogg', audio_file, 'audio/ogg; codecs=opus'),
        }
        
        data = {
            'messaging_product': 'whatsapp'
        }
        
        upload_response = requests.post(upload_url, headers=headers, files=files, data=data)
        upload_response.raise_for_status()
        media_id = upload_response.json().get('id')
        
        if not media_id:
            return None
        
        # Step 2: Send audio message
        send_url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "audio",
            "audio": {
                "id": media_id
            }
        }
        
        response = requests.post(send_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    
    except requests.exceptions.RequestException as e:
        import traceback
        traceback.print_exc()
        return None


def send_whatsapp_message(phone_number, message):
    """Send a WhatsApp text message using the Facebook Graph API"""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return None


def mark_message_read(message_id):
    """Mark a message as read"""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }
    
    try:
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"Error marking message as read: {e}")
