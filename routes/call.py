from . import call_bp
import os
from dotenv import load_dotenv
import os
import wave

from flask import Flask, current_app, render_template, request, jsonify
from twilio.twiml.voice_response import VoiceResponse
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant



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

@call_bp.route("/get-files")
def get_sys_files():
    # return current_app.bot._process_files(admin_id="67e9dfe8-5715-499c-b34b-219fa24971cb")
    return  current_app.bot._process_files(admin_id="f7fe50c3-bba5-4cc0-9551-69b433079521")

