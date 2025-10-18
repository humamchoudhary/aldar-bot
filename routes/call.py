from flask import render_template, session, request, jsonify, redirect, url_for, current_app
from flask_socketio import join_room, leave_room, emit
from . import call_bp
import wave
import os
import time
import io
import subprocess
import tempfile
import threading
import pyaudio

gemini_sessions = {}
data = []

current_wave = None
file_path = None

audio_buffers = {}
client_states = {}

# PyAudio for live playback
p = pyaudio.PyAudio()

audio_buffer = io.BytesIO()

@call_bp.route("/")
def index():
    return render_template("call/index.html")

def play_audio_stream(audio_data, client_sid):
    """Play audio stream in real-time"""
    try:
        # Save WebM to temporary file
        temp_webm = f"temp_playback_{client_sid}.webm"
        with open(temp_webm, 'wb') as f:
            f.write(audio_data)
        
        # Convert WebM to raw PCM for playback
        ffmpeg_process = subprocess.Popen([
            'ffmpeg', '-i', temp_webm,
            '-f', 's16le',         # Raw PCM
            '-acodec', 'pcm_s16le',
            '-ac', '1',            # Mono
            '-ar', '44100',        # Sample rate
            '-loglevel', 'quiet',
            'pipe:1'
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # PyAudio stream configuration
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=44100,
            output=True,
            frames_per_buffer=1024
        )
        
        # Stream audio data
        while True:
            data = ffmpeg_process.stdout.read(1024)
            if not data:
                break
            stream.write(data)
        
        # Cleanup
        stream.stop_stream()
        stream.close()
        ffmpeg_process.wait()
        os.remove(temp_webm)
        
        print(f"✅ Finished playing audio for {client_sid}")
        
    except Exception as e:
        print(f"❌ Error playing audio: {e}")

def register_call_socketio_events(socketio):
    @socketio.on('connect')
    def handle_connect():
        print(f"Client connected: {request.sid}")
        # Initialize buffer and state for this client
        audio_buffers[request.sid] = io.BytesIO()
        client_states[request.sid] = {
            'last_audio_time': time.time(),
            'is_silent': False
        }

    @socketio.on('audio_chunk')
    def handle_audio_chunk(data):
        """Save incoming audio chunks to buffer and play live"""
        try:
            if request.sid in audio_buffers:
                # Write the binary audio data to buffer
                audio_buffers[request.sid].write(data)
                
                # Update last audio time (user is speaking)
                client_states[request.sid]['last_audio_time'] = time.time()
                client_states[request.sid]['is_silent'] = False
                
                # Play audio chunk live (in a separate thread to not block)
                threading.Thread(
                    target=play_audio_chunk_live,
                    args=(data, request.sid)
                ).start()
                
                print(f"Received audio chunk: {len(data)} bytes")
                
        except Exception as e:
            print(f"Error handling audio chunk: {e}")

    def play_audio_chunk_live(audio_data, client_sid):
        """Play a single audio chunk live"""
        try:
            # Convert WebM chunk to PCM and play immediately
            ffmpeg_process = subprocess.Popen([
                'ffmpeg', 
                '-i', 'pipe:0',        # Input from stdin
                '-f', 's16le',         # Raw PCM output
                '-acodec', 'pcm_s16le',
                '-ac', '1',
                '-ar', '44100',
                '-loglevel', 'quiet',
                'pipe:1'
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Feed audio data to ffmpeg
            pcm_data, _ = ffmpeg_process.communicate(input=audio_data)
            
            # Play PCM data
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=44100,
                output=True,
                frames_per_buffer=1024
            )
            
            stream.write(pcm_data)
            stream.stop_stream()
            stream.close()
            
        except Exception as e:
            print(f"Error playing audio chunk: {e}")

    @socketio.on('silence_detected')
    def handle_silence_detected():
        """Client detected silence - save the recording"""
        save_recording(request.sid, "auto")

    @socketio.on('save_recording')
    def handle_save_recording():
        """Manual save recording"""
        save_recording(request.sid, "manual")

    def save_recording(client_sid, save_type):
        """Save recording and play it back"""
        try:
            if client_sid not in audio_buffers or audio_buffers[client_sid].tell() == 0:
                print("No audio data to save")
                return
            
            buffer = audio_buffers[client_sid]
            buffer.seek(0)
            webm_data = buffer.getvalue()
            
            if not webm_data:
                print("Empty audio buffer")
                return
            
            # Save WebM data temporarily
            temp_webm = f"temp_{client_sid}.webm"
            with open(temp_webm, 'wb') as f:
                f.write(webm_data)
            
            # Convert WebM to WAV using ffmpeg WITH VOLUME BOOST
            wav_filename = f"recordings/recording_{int(time.time())}.wav"
            
            result = subprocess.run([
                'ffmpeg', '-y', '-i', temp_webm,
                '-af', 'volume=3.0',  # Volume boost
                '-acodec', 'pcm_s16le',
                '-ac', '1',
                '-ar', '44100',
                wav_filename
            ], capture_output=True, text=True)
            
            # Play the full recording after saving
            threading.Thread(
                target=play_audio_stream,
                args=(webm_data, client_sid)
            ).start()
            
            # Clean up temporary file
            try:
                os.remove(temp_webm)
            except:
                pass
            
            if result.returncode == 0:
                print(f"✅ {save_type.capitalize()}-saved WAV file: {wav_filename}")
                
                # Verify file was created
                if os.path.exists(wav_filename):
                    file_size = os.path.getsize(wav_filename)
                    print(f"✅ WAV file size: {file_size} bytes")
                    
                    # Notify client that file was saved
                    emit('recording_saved', {
                        'filename': wav_filename, 
                        'save_type': save_type,
                        'file_size': file_size
                    }, room=client_sid)
                else:
                    print("❌ WAV file was not created")
                    
            else:
                print(f"❌ FFmpeg conversion failed: {result.stderr}")
            
            # Reset buffer
            audio_buffers[client_sid] = io.BytesIO()
            client_states[client_sid]['last_audio_time'] = time.time()
            
        except Exception as e:
            print(f"Error saving recording: {e}")

    @socketio.on('disconnect')
    def handle_disconnect():
        print(f"Client disconnected: {request.sid}")
        # Clean up
        if request.sid in audio_buffers:
            del audio_buffers[request.sid]
        if request.sid in client_states:
            del client_states[request.sid]

# Cleanup PyAudio on exit
import atexit
@atexit.register
def cleanup():
    p.terminate()
