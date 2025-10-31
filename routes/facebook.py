from flask import Flask, current_app, render_template, request, jsonify
import requests
import os
from io import BytesIO
from pydub import AudioSegment
from datetime import datetime, timedelta

from services.admin_service import AdminService
from services.facebook_service import FacebookService
from . import fb_bp

FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
VERIFY_TOKEN = os.getenv('FB_VERIFY_TOKEN', 'your_fb_verify_token_here')
VERSION = 'v21.0'
DEFAULT_ADMIN_ID = os.getenv("DEFAULT_ADMIN_ID")

# Store processed message IDs with timestamps
processed_messages = {}
MESSAGE_CACHE_DURATION = timedelta(hours=1)


def cleanup_old_messages():
    """Remove message IDs older than MESSAGE_CACHE_DURATION"""
    current_time = datetime.now()
    expired_ids = [
        msg_id for msg_id, timestamp in processed_messages.items()
        if current_time - timestamp > MESSAGE_CACHE_DURATION
    ]
    for msg_id in expired_ids:
        del processed_messages[msg_id]


def is_duplicate_message(message_id):
    """Check if message has already been processed"""
    cleanup_old_messages()
    
    if message_id in processed_messages:
        return True
    
    processed_messages[message_id] = datetime.now()
    return False


@fb_bp.route('/webhook', methods=['GET'])
def verify_webhook():
    """Verify webhook for Facebook Messenger"""
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        print("Facebook webhook verified successfully!")
        return challenge, 200
    else:
        print("Facebook webhook verification failed!")
        return "Forbidden", 403


def detect_audio_format(audio_data):
    """Detect audio format from file signature (magic bytes)"""
    if len(audio_data) < 12:
        return None
    
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


def convert_audio_for_messenger(audio_data):
    """Convert audio data to MP3 format for Messenger"""
    try:
        detected_format = detect_audio_format(audio_data)
        print(f"Detected audio format: {detected_format}")
        
        audio_buffer = BytesIO(audio_data)
        
        try:
            if detected_format:
                audio = AudioSegment.from_file(audio_buffer, format=detected_format)
            else:
                audio = None
                for fmt in ['mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac']:
                    try:
                        audio_buffer.seek(0)
                        audio = AudioSegment.from_file(audio_buffer, format=fmt)
                        print(f"Successfully loaded as {fmt}")
                        break
                    except:
                        continue
                
                if audio is None:
                    raise ValueError("Could not detect audio format")
        except Exception as e:
            print(f"Error loading audio: {e}")
            try:
                audio_buffer.seek(0)
                audio = AudioSegment(
                    data=audio_data,
                    sample_width=2,
                    frame_rate=24000,
                    channels=1
                )
                print("Loaded as raw PCM data")
            except:
                raise
        
        if audio.channels > 1:
            audio = audio.set_channels(1)
        
        audio = audio.set_frame_rate(16000)
        
        output_buffer = BytesIO()
        audio.export(output_buffer, format='mp3', bitrate='128k')
        
        output_buffer.seek(0)
        return output_buffer.read()
    
    except Exception as e:
        print(f"Error converting audio to MP3: {e}")
        import traceback
        traceback.print_exc()
        return None


@fb_bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Facebook Messenger messages"""
    try:
        data = request.get_json()
        print("Received Facebook webhook data:", data)
        fb_service = FacebookService(current_app.db)
        
        if data.get('object') == 'page':
            entries = data.get('entry', [])
            
            for entry in entries:
                messaging_events = entry.get('messaging', [])
                
                for event in messaging_events:
                    sender_id = event.get('sender', {}).get('id')
                    recipient_id = event.get('recipient', {}).get('id')
                    
                    # Handle messages
                    if 'message' in event:
                        message = event['message']
                        message_id = message.get('mid')
                        
                        # Check for duplicate
                        if is_duplicate_message(message_id):
                            print(f"Ignoring duplicate message: {message_id}")
                            continue
                        
                        # Get or create chat
                        chat = fb_service.get_by_sender_id(sender_id)
                        admin = AdminService(current_app.db).get_admin_by_id(DEFAULT_ADMIN_ID)
                        
                        if not chat:
                            fb_service.create(sender_id)
                            current_app.bot.create_chat(sender_id, admin)
                            print(f"New Facebook user: {sender_id}")
                        
                        # Handle text messages
                        if 'text' in message:
                            user_message = message['text']
                            print(f"Received text from {sender_id}: {user_message}")
                            
                            fb_service.add_message(user_message, sender_id, sender_id, type="text")
                            
                            msg, usage = current_app.bot.respond(f"Message from facebook: {user_message}", sender_id)
                            print(f"Bot response: {msg}")
                            
                            fb_service.add_message(msg, sender_id, "bot", type="text")
                            send_messenger_message(sender_id, msg)
                        
                        # Handle audio attachments
                        elif 'attachments' in message:
                            attachments = message['attachments']
                            
                            for attachment in attachments:
                                if attachment.get('type') == 'audio':
                                    audio_url = attachment.get('payload', {}).get('url')
                                    print(f"Received audio from {sender_id}: {audio_url}")
                                    
                                    # Download audio
                                    audio_bytes = download_messenger_media(audio_url)
                                    
                                    if audio_bytes:
                                        print(f"Downloaded audio: {len(audio_bytes)} bytes")
                                        
                                        # Transcribe
                                        transcribed_text = current_app.bot.transcribe(audio_bytes)
                                        print(f"Transcribed: {transcribed_text}")
                                        
                                        # Save user audio message
                                        msg_id = fb_service.add_message(
                                                f"Message from facebook: {transcribed_text}", sender_id, sender_id, type="audio"
                                        )
                                        
                                        # Save audio file
                                        save_path = os.path.join('files', 'facebook', f"{sender_id}", f"{msg_id}.mp3")
                                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                                        
                                        with open(save_path, 'wb') as f:
                                            f.write(audio_bytes)
                                        print(f"Saved audio to: {save_path}")
                                        
                                        # Get bot response
                                        msg, usage = current_app.bot.respond(transcribed_text, sender_id)
                                        print(f"Bot response: {msg}")
                                        
                                        # Generate audio response
                                        audio_response = current_app.bot.generate_audio(msg)
                                        print(f"Generated audio: {len(audio_response)} bytes")
                                        
                                        # Convert to MP3
                                        mp3_audio = convert_audio_for_messenger(audio_response)
                                        
                                        if mp3_audio:
                                            # Save bot audio
                                            bot_msg_id = fb_service.add_message(
                                                msg, sender_id, "bot", type="audio"
                                            )
                                            bot_audio_path = os.path.join(
                                                'files', 'facebook', f"{sender_id}", f"{bot_msg_id}.mp3"
                                            )
                                            
                                            with open(bot_audio_path, 'wb') as f:
                                                f.write(mp3_audio)
                                            print(f"Saved bot audio to: {bot_audio_path}")
                                            
                                            # Send audio response
                                            send_messenger_audio(sender_id, mp3_audio)
                                        else:
                                            print("Failed to convert audio")
                                            send_messenger_message(sender_id, msg)
                                    else:
                                        print(f"Failed to download audio from {sender_id}")
                                        send_messenger_message(
                                            sender_id, 
                                            "Sorry, I couldn't process your audio message."
                                        )
                    
                    # Handle delivery confirmations (optional)
                    elif 'delivery' in event:
                        pass  # Message was delivered
                    
                    # Handle read receipts (optional)
                    elif 'read' in event:
                        pass  # Message was read
        
        return jsonify({"status": "success"}), 200
    
    except Exception as e:
        print(f"Error processing Facebook webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def download_messenger_media(media_url):
    """Download media file from Messenger"""
    try:
        print(f"Downloading media from: {media_url}")
        response = requests.get(media_url)
        response.raise_for_status()
        
        print(f"Successfully downloaded media: {len(response.content)} bytes")
        return response.content
    
    except requests.exceptions.RequestException as e:
        print(f"Error downloading media: {e}")
        import traceback
        traceback.print_exc()
        return None


def send_messenger_audio(recipient_id, audio_data):
    """Send audio message via Messenger"""
    try:
        url = f"https://graph.facebook.com/{VERSION}/me/messages"
        
        # Create multipart form data
        files = {
            'filedata': ('audio.mp3', BytesIO(audio_data), 'audio/mpeg')
        }
        
        data = {
            'recipient': f'{{"id":"{recipient_id}"}}',
            'message': '{"attachment":{"type":"audio", "payload":{"is_reusable":true}}}',
            'access_token': FACEBOOK_PAGE_ACCESS_TOKEN
        }
        
        print(f"Uploading and sending audio to {recipient_id} ({len(audio_data)} bytes)...")
        response = requests.post(url, files=files, data=data)
        response.raise_for_status()
        
        print(f"Audio sent successfully to {recipient_id}")
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"Error sending audio: {e}")
        import traceback
        traceback.print_exc()
        return None


def send_messenger_message(recipient_id, message):
    """Send a text message via Messenger"""
    url = f"https://graph.facebook.com/{VERSION}/me/messages"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": message
        },
        "access_token": FACEBOOK_PAGE_ACCESS_TOKEN
    }
    
    print(f"Sending message to {recipient_id}: {message}")
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error sending message: {e}")
        return None


def send_typing_indicator(recipient_id, action="typing_on"):
    """Send typing indicator to show bot is processing"""
    url = f"https://graph.facebook.com/{VERSION}/me/messages"
    
    payload = {
        "recipient": {
            "id": recipient_id
        },
        "sender_action": action,
        "access_token": FACEBOOK_PAGE_ACCESS_TOKEN
    }
    
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending typing indicator: {e}")
