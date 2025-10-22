from services.call_service import CallService
from . import call_bp
# import os
# from dotenv import load_dotenv
# import os
# import wave
#
# from flask import Flask, current_app, render_template, request, jsonify
# from twilio.jwt.access_token import AccessToken
# from twilio.jwt.access_token.grants import VoiceGrant
# from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
#
# from flask import Flask, request, Response
# # Load environment variables from .env file
# load_dotenv()
#
# # Retrieve Twilio credentials
# TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
# TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
# TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
# TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")
#
#
# @call_bp.route('/')
# def index():
#     return render_template('call/index.html')
#
#
#
#
# #
# @call_bp.route('/token', methods=['GET'])
# def generate_token():
#     """Generate an access token for Twilio Client"""
#     identity = 'userbrowser'
#     
#     # Create access token
#     token = AccessToken(
#         TWILIO_ACCOUNT_SID,
#         TWILIO_API_KEY,
#         TWILIO_API_SECRET,
#         identity=identity
#     )
#     
#     # Create a Voice grant and add to token
#     voice_grant = VoiceGrant(
#         outgoing_application_sid=TWILIO_TWIML_APP_SID,
#         incoming_allow=True
#     )
#     token.add_grant(voice_grant)
#     
#     return jsonify({'token': token.to_jwt()})
#
# @call_bp.route("/voice")
# def get_voice():
#     print(request.values)
#     # caller_number = 
#     # print(caller_number)
#
#     response = VoiceResponse()
#
#     # Add a greeting message
#     response.say("Hi, how may I help you?", voice="Google.en-US-Chirp3-HD-Kore")
#
#     # Connect to your WebSocket stream
#     connect = Connect()
#     stream = connect.stream(url="wss://al-dar-call.go-globe.dev/")
#
#     stream.parameter(name='From', value=f'{request.values.get('From', None)}')
#
#     stream.parameter(name='name', value=f'{request.values.get('name', None)}')
#     stream.parameter(name='qid', value=f'{request.values.get('qid', None)}')
#     response.append(connect)
#
#     # Print or return the TwiML
#     print(str(response))
#
#     return Response(str(response), mimetype="text/xml")
#
# @call_bp.route("/get-files")
# def get_sys_files():
#     return current_app.bot._process_files(admin_id="4258fbdf-3f75-4446-91b5-1f3780a79c07")
#     # return  current_app.bot._process_files(admin_id="f7fe50c3-bba5-4cc0-9551-69b433079521")
#
#
#
#
#
# # Store call sessions in memory (use database in production)
# call_sessions = {}
#
# @call_bp.route('/log/<call_uuid>', methods=['POST'])
# def initialize_call(call_uuid):
#     """
#     Initialize a new call session
#     """
#     data = request.get_json()
#     
#     print("=" * 60)
#     print(f"📞 NEW CALL INITIALIZED")
#     print("=" * 60)
#     print(f"Call UUID: {call_uuid}")
#     print(f"File Name: {data.get('file_name')}")
#     print(f"Started At: {data.get('started_at')}")
#     print(data)
#     print("=" * 60)
#     
#     try:
#         call_service = CallService(current_app.db)
#         call_service.create_call(call_uuid, data)
#         
#         return jsonify({
#             "status": "success",
#             "message": "Call session initialized",
#             "call_uuid": call_uuid
#         }), 200
#     
#     except Exception as e:
#         print(f"❌ Error initializing call: {e}")
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500
#
#
# @call_bp.route('/log/<call_uuid>/send_chunk', methods=['POST'])
# def receive_chunk(call_uuid):
#     """
#     Receive transcription chunks for an ongoing call
#     """
#     data = request.get_json()
#     
#     in_transcriptions = data.get('transcription', [])
#     is_final = data.get('is_final', False)
#     chunk_index = data.get('chunk_index', 0)
#     
#     print("\n" + "=" * 60)
#     print(f"📦 CHUNK RECEIVED - Call: {call_uuid[:8]}...")
#     print("=" * 60)
#     print(f"Chunk Index: {chunk_index}")
#     print(f"New Messages: {len(in_transcriptions)}")
#     print(f"Is Final: {is_final}")
#     print("-" * 60)
#     
#     # Merge consecutive messages from the same speaker
#     merged_transcription = []
#     last_entry = None
#     
#     for msg in in_transcriptions:
#         speaker = msg.get('name', 'UNKNOWN').upper()
#         text = msg.get('transcription', '').strip()
#         
#         if not text:
#             continue  # Skip empty transcriptions
#         
#         emoji = "👤" if speaker == "USER" else "🤖"
#         print(f"{emoji} {speaker}: {text}")
#         
#         # If same speaker as previous message, append text
#         if last_entry and last_entry["speaker"] == speaker:
#             last_entry["transcription"] += " " + text
#         else:
#             # Start a new transcription entry
#             last_entry = {"speaker": speaker, "transcription": text}
#             merged_transcription.append(last_entry)
#     
#     print("-" * 60)
#     print(f"Merged into {len(merged_transcription)} entries")
#     print("=" * 60)
#     
#     try:
#         call_service = CallService(current_app.db)
#         call_service.add_chunk(call_uuid, merged_transcription)
#         
#         # If this is the final chunk, mark call as ended
#         if is_final:
#             call_service.end_call(call_uuid)
#             print(f"\n🏁 CALL COMPLETED: {call_uuid[:8]}...")
#             print("=" * 60 + "\n")
#         
#         return jsonify({
#             "status": "success",
#             "message": "Chunk received",
#             "chunk_index": chunk_index,
#             "messages_count": len(in_transcriptions),
#             "merged_count": len(merged_transcription)
#         }), 200
#     
#     except Exception as e:
#         print(f"❌ Error processing chunk: {e}")
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500
#
#
# @call_bp.route('/log/<call_uuid>/summary', methods=['GET'])
# def get_call_summary(call_uuid):
#     """
#     Get complete summary of a call
#     """
#     try:
#         call_service = CallService(current_app.db)
#         call = call_service.get_call(call_uuid)
#         
#         if not call:
#             return jsonify({
#                 "status": "error",
#                 "message": "Call not found"
#             }), 404
#         
#         # Convert ObjectId to string for JSON serialization
#         call['_id'] = str(call['_id'])
#         
#         return jsonify({
#             "status": "success",
#             "call": call
#         }), 200
#     
#     except Exception as e:
#         print(f"❌ Error getting call summary: {e}")
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500
#
#
# @call_bp.route('/log/active-calls', methods=['GET'])
# def get_active_calls():
#     """
#     Get list of all calls
#     """
#     try:
#         call_service = CallService(current_app.db)
#         calls = list(call_service.call_collection.find({}))
#         
#         # Convert ObjectId to string for JSON serialization
#         for call in calls:
#             call['_id'] = str(call['_id'])
#         
#         return jsonify({
#             "status": "success",
#             "total_calls": len(calls),
#             "calls": calls
#         }), 200
#     
#     except Exception as e:
#         print(f"❌ Error getting active calls: {e}")
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500



from flask import Flask, render_template, request, jsonify, Response
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream
import os
import requests
from dotenv import load_dotenv

load_dotenv()


# Twilio credentials
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_API_KEY = os.getenv("TWILIO_API_KEY")
TWILIO_API_SECRET = os.getenv("TWILIO_API_SECRET")
TWILIO_TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID")

# Quart Gemini server URL
QUART_SERVER_URL = os.getenv("QUART_SERVER_URL", "https://al-dar-call.go-globe.dev")

# Initialize Twilio client
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Track admin transfers
active_transfers = {}


@call_bp.route('/admin/token', methods=['GET'])
def get_admin_token():
    """Generate Twilio access token for admin"""
    from uuid import uuid4
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


@call_bp.route('/admin/request-transfer', methods=['POST'])
def request_transfer():
    """Admin requests to take over a call"""
    data = request.get_json()
    call_uuid = data.get('call_uuid')
    call_sid = data.get('call_sid')
    
    if not call_uuid or not call_sid:
        return jsonify({"success": False, "error": "Missing call_uuid or call_sid"}), 400
    
    try:
        # Get call info from Quart server
        response = requests.get(f"{QUART_SERVER_URL}/api/get-call-info/{call_uuid}")
        
        if response.status_code != 200:
            return jsonify({"success": False, "error": "Call not found"}), 404
        
        call_info = response.json()
        customer_info = call_info.get('customer_info', {})
        
        # Use Twilio API to redirect the call to admin stream
        twilio_client.calls(call_sid).update(
            twiml=f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Joanna">Please hold while we connect you to a representative.</Say>
    <Pause length="1"/>
    <Connect>
        <Stream url="wss://{QUART_SERVER_URL.replace('https://', '').replace('http://', '')}/admin-stream/{call_uuid}">
            <Parameter name="call_uuid" value="{call_uuid}" />
            <Parameter name="admin_transfer" value="true" />
        </Stream>
    </Connect>
</Response>'''
        )
        
        # Track this transfer
        active_transfers[call_uuid] = {
            'call_sid': call_sid,
            'customer_info': customer_info,
            'status': 'transferred'
        }
        
        print(f"✅ Call {call_sid} redirected to admin stream")
        
        return jsonify({
            "success": True,
            "call_uuid": call_uuid,
            "customer_info": customer_info
        })
        
    except Exception as e:
        print(f"❌ Error redirecting call: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@call_bp.route('/admin/end-call', methods=['POST'])
def end_call():
    """Admin ends the call"""
    data = request.get_json()
    call_uuid = data.get('call_uuid')
    
    if call_uuid in active_transfers:
        call_sid = active_transfers[call_uuid]['call_sid']
        
        try:
            # End the Twilio call
            twilio_client.calls(call_sid).update(status='completed')
            del active_transfers[call_uuid]
            
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    return jsonify({"success": False, "error": "Call not found"}), 404


@call_bp.route('/admin-voice', methods=['POST'])
def admin_voice():
    """TwiML endpoint for admin calls"""
    call_uuid = request.values.get('call_uuid')
    admin_join = request.values.get('admin_join')
    
    if not call_uuid:
        response = VoiceResponse()
        response.say('Call not found or has ended.')
        response.hangup()
        return Response(str(response), mimetype='text/xml')
    
    # Check if call exists
    try:
        call_response = requests.get(f"{QUART_SERVER_URL}/api/get-call-info/{call_uuid}")
        if call_response.status_code != 200:
            response = VoiceResponse()
            response.say('Call not found or has ended.')
            response.hangup()
            return Response(str(response), mimetype='text/xml')
    except:
        response = VoiceResponse()
        response.say('Unable to connect to call.')
        response.hangup()
        return Response(str(response), mimetype='text/xml')
    
    # Create TwiML to connect admin to the call's stream
    response = VoiceResponse()
    connect = Connect()
    
    # Admin connects to a separate stream endpoint on Quart server
    stream = Stream(url=f"wss://{QUART_SERVER_URL.replace('https://', '').replace('http://', '')}/admin-stream/{call_uuid}")
    stream.parameter(name='call_uuid', value=call_uuid)
    stream.parameter(name='admin', value='true')
    
    connect.append(stream)
    response.append(connect)
    
    return Response(str(response), mimetype='text/xml')


@call_bp.route('/api/call-event', methods=['POST'])
def handle_call_event():
    """Receive call events from Quart Gemini server"""
    data = request.get_json()
    call_uuid = data.get('call_uuid')
    event = data.get('event')
    
    print(f"📨 Received event from Quart: {event} for call {call_uuid}")
    
    # You can add custom logic here based on events
    # e.g., notify admins, update database, send webhooks, etc.
    
    if event == "transfer_requested":
        print(f"🔔 Transfer requested for call {call_uuid}")
        # You could trigger notifications to admins here
    
    elif event == "call_started":
        print(f"📞 New call started: {call_uuid}")
    
    elif event == "call_ended":
        print(f"🏁 Call ended: {call_uuid}")
        if call_uuid in active_transfers:
            del active_transfers[call_uuid]
    
    return jsonify({"success": True})


@call_bp.route('/calls')
def calls():
    return render_template('call/admin-calls.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
