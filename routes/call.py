from services.call_service import CallService
from . import call_bp
import os
from dotenv import load_dotenv
import os
import wave

from flask import Flask, current_app, render_template, request, jsonify
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from flask import Flask, request, Response
# Load environment variables from .env file
load_dotenv()

# Retrieve Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")


@call_bp.route('/')
def index():
    return render_template('call/index.html')


#
@call_bp.route('/token', methods=['GET'])
def generate_token():
    """Generate an access token for Twilio Client"""
    identity = 'userbrowser'
    
    # Create access token
    token = AccessToken(
        TWILIO_ACCOUNT_SID,
        TWILIO_API_KEY,
        TWILIO_API_SECRET,
        identity=identity
    )
    
    # Create a Voice grant and add to token
    voice_grant = VoiceGrant(
        outgoing_application_sid=TWILIO_TWIML_APP_SID,
        incoming_allow=True
    )
    token.add_grant(voice_grant)
    
    return jsonify({'token': token.to_jwt()})

@call_bp.route("/voice")
def get_voice():
    print(request.values)
    # caller_number = 
    # print(caller_number)

    response = VoiceResponse()

    # Add a greeting message
    response.say("Hi, how may I help you?", voice="Google.en-US-Chirp3-HD-Kore")

    # Connect to your WebSocket stream
    connect = Connect()
    stream = connect.stream(url="wss://al-dar-call.go-globe.dev/")

    stream.parameter(name='From', value=f'{request.values.get('From', None)}')

    stream.parameter(name='name', value=f'{request.values.get('name', None)}')
    stream.parameter(name='qid', value=f'{request.values.get('name', None)}')
    response.append(connect)

    # Print or return the TwiML
    print(str(response))

    return Response(str(response), mimetype="text/xml")

@call_bp.route("/get-files")
def get_sys_files():
    return current_app.bot._process_files(admin_id="4258fbdf-3f75-4446-91b5-1f3780a79c07")
    # return  current_app.bot._process_files(admin_id="f7fe50c3-bba5-4cc0-9551-69b433079521")





# Store call sessions in memory (use database in production)
call_sessions = {}

@call_bp.route('/log/<call_uuid>', methods=['POST'])
def initialize_call(call_uuid):
    """
    Initialize a new call session
    """
    data = request.get_json()
    
    print("=" * 60)
    print(f"📞 NEW CALL INITIALIZED")
    print("=" * 60)
    print(f"Call UUID: {call_uuid}")
    print(f"File Name: {data.get('file_name')}")
    print(f"Started At: {data.get('started_at')}")
    print(data)
    print("=" * 60)
    
    try:
        call_service = CallService(current_app.db)
        call_service.create_call(call_uuid, data)
        
        return jsonify({
            "status": "success",
            "message": "Call session initialized",
            "call_uuid": call_uuid
        }), 200
    
    except Exception as e:
        print(f"❌ Error initializing call: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@call_bp.route('/log/<call_uuid>/send_chunk', methods=['POST'])
def receive_chunk(call_uuid):
    """
    Receive transcription chunks for an ongoing call
    """
    data = request.get_json()
    
    in_transcriptions = data.get('transcription', [])
    is_final = data.get('is_final', False)
    chunk_index = data.get('chunk_index', 0)
    
    print("\n" + "=" * 60)
    print(f"📦 CHUNK RECEIVED - Call: {call_uuid[:8]}...")
    print("=" * 60)
    print(f"Chunk Index: {chunk_index}")
    print(f"New Messages: {len(in_transcriptions)}")
    print(f"Is Final: {is_final}")
    print("-" * 60)
    
    # Merge consecutive messages from the same speaker
    merged_transcription = []
    last_entry = None
    
    for msg in in_transcriptions:
        speaker = msg.get('name', 'UNKNOWN').upper()
        text = msg.get('transcription', '').strip()
        
        if not text:
            continue  # Skip empty transcriptions
        
        emoji = "👤" if speaker == "USER" else "🤖"
        print(f"{emoji} {speaker}: {text}")
        
        # If same speaker as previous message, append text
        if last_entry and last_entry["speaker"] == speaker:
            last_entry["transcription"] += " " + text
        else:
            # Start a new transcription entry
            last_entry = {"speaker": speaker, "transcription": text}
            merged_transcription.append(last_entry)
    
    print("-" * 60)
    print(f"Merged into {len(merged_transcription)} entries")
    print("=" * 60)
    
    try:
        call_service = CallService(current_app.db)
        call_service.add_chunk(call_uuid, merged_transcription)
        
        # If this is the final chunk, mark call as ended
        if is_final:
            call_service.end_call(call_uuid)
            print(f"\n🏁 CALL COMPLETED: {call_uuid[:8]}...")
            print("=" * 60 + "\n")
        
        return jsonify({
            "status": "success",
            "message": "Chunk received",
            "chunk_index": chunk_index,
            "messages_count": len(in_transcriptions),
            "merged_count": len(merged_transcription)
        }), 200
    
    except Exception as e:
        print(f"❌ Error processing chunk: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@call_bp.route('/log/<call_uuid>/summary', methods=['GET'])
def get_call_summary(call_uuid):
    """
    Get complete summary of a call
    """
    try:
        call_service = CallService(current_app.db)
        call = call_service.get_call(call_uuid)
        
        if not call:
            return jsonify({
                "status": "error",
                "message": "Call not found"
            }), 404
        
        # Convert ObjectId to string for JSON serialization
        call['_id'] = str(call['_id'])
        
        return jsonify({
            "status": "success",
            "call": call
        }), 200
    
    except Exception as e:
        print(f"❌ Error getting call summary: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@call_bp.route('/log/active-calls', methods=['GET'])
def get_active_calls():
    """
    Get list of all calls
    """
    try:
        call_service = CallService(current_app.db)
        calls = list(call_service.call_collection.find({}))
        
        # Convert ObjectId to string for JSON serialization
        for call in calls:
            call['_id'] = str(call['_id'])
        
        return jsonify({
            "status": "success",
            "total_calls": len(calls),
            "calls": calls
        }), 200
    
    except Exception as e:
        print(f"❌ Error getting active calls: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
