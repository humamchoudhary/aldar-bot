from pprint import pprint
from services.expo_noti import send_push_noti
import markdown
from flask import make_response
from services.notification_service import NotificationService
from flask_mail import Mail
from services.admin_service import AdminService
from datetime import datetime
import requests
from services.timezone import UTCZoneManager
from flask import render_template_string
from services.usage_service import UsageService
import random
from flask import render_template, session, request, jsonify, redirect, url_for, current_app
from flask_socketio import join_room, leave_room, emit
from . import min_bp
from services.user_service import UserService
from services.chat_service import ChatService
from functools import wraps
from services.email_service import send_email
import os
import pytz


@min_bp.before_request
def before_req():
    path = str(request.path)
    print(session.items())
    print(f"Path: {path}")
    print(f"LastVisit: {session.get('last_visit')}")
    if path.startswith("/min") and (path.split("/")[-1] not in ['auth', 'send_message', 'ping_admin',"send_audio"] and path not in ['/min/', '/min/get-headers'] and "audio_file" not in path):
        session["last_visit"] = path


# Add a login_required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for("min.index"))

        user_service = UserService(current_app.db)
        user = user_service.get_user_by_id(session['user_id'])

        if not user:
            return redirect(url_for("min.index"))
        return f(*args, **kwargs)
    return decorated_function


@min_bp.route('/get-headers')
def headers():
    return render_template('user/min-headers.html')


@min_bp.route('/')
def index():
    if 'last_visit' in session and session['last_visit'] not in ['/min/', '/min/get-headers']:
        return redirect(session['last_visit'])
    
    return redirect('/min/onboarding')


@min_bp.route('login', defaults={'subject': None}, methods=['GET'])
@min_bp.route('login/<string:subject>', methods=['GET'])
def login(subject):
    if request.method == "GET":
        try:
            ip = request.headers.get("X-Real-IP", request.remote_addr)
            ip = ip.split(",")[0]

            geo = requests.get(f"http://ipleak.net/json/{ip}", timeout=3)
            geo = geo.json()
            country = geo.get("country_name", None)
        except Exception as e:
            print(f"Geo lookup error: {e}")
            country = None
        return render_template('user/min-login.html', default_subject=subject, user_country=country)


@min_bp.route('onboarding', methods=['GET'])
def onboard():
    # Clear last_visit when returning to onboarding
    session.pop('last_visit', None)
    return render_template('user/min-onboard.html')


def generate_random_username():
    return f"user_{random.randint(1000, 9999)}"


@min_bp.route('/auth', methods=['POST', 'GET'])
def auth_user():
    is_htmx = request.headers.get('HX-Request') == 'true'

    if request.content_type == 'application/json':
        data = request.json or {}
    else:
        data = request.form.to_dict() or {}
    
    name = data.get('name')
    email = data.get('email', "")
    phone = data.get('phone', " ")
    subject = data.get('subject')
    desg = data.get('desg', " ")
    is_anon = data.get('anonymous')
    __import__('pprint').pprint(data)
    
    user_ip = request.headers.get("X-Real-IP", request.remote_addr).split(",")[0]
    user_service = UserService(current_app.db)

    if is_anon:
        name = generate_random_username()
        user = user_service.create_user(name, ip=user_ip)
    else:
        user = user_service.create_user(
            name, email=email, phone=phone, ip=user_ip, desg=desg)

    if not (name or email or phone):
        if not True:  # Replace with your ALLOW_EMPTY_USERS check
            error_message = {"error": "Empty users are not allowed."}
            if is_htmx:
                return jsonify(error_message), 400
            return jsonify(error_message), 400
        name = generate_random_username()

    session['user_id'] = user.user_id
    session['role'] = "user"

    return redirect(url_for('min.new_chat', subject=subject))


@min_bp.route('/newchat', defaults={'subject': "Other"}, methods=['GET'])
@min_bp.route('/newchat/<string:subject>', methods=['GET'])
@login_required
def new_chat(subject):
    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(session['user_id'])
    chat_service = ChatService(current_app.db)
    
    chat = chat_service.create_chat(
        user.user_id, subject=subject, admin_id=session.get('admin_id'))
    user_service.add_chat_to_user(user.user_id, chat.chat_id)

    admin = AdminService(current_app.db).get_admin_by_id(session.get('admin_id'))
    current_app.bot.create_chat(chat.room_id, admin)

    # Clear last_visit to prevent returning to old chat
    session.pop('last_visit', None)
    
    # Redirect to chat using room_id (consistent!)
    return redirect(url_for('min.chat', room_id=chat.room_id))


@min_bp.route('/chat/<string:room_id>', methods=['GET'])
@login_required
def chat(room_id):
    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(session['user_id'])

    chat_service = ChatService(current_app.db)
    chat = chat_service.get_chat_by_room_id(room_id)
    
    if not chat:
        print(f"Chat not found for room_id: {room_id}")
        # Clear invalid last_visit
        session.pop('last_visit', None)
        if request.headers.get('HX-Request') == 'true':
            return redirect(url_for("min.onboard"))
        return redirect(url_for("min.onboard"))

    # Security check - verify chat belongs to user
    if not chat.room_id.startswith(user.user_id):
        print(f"Unauthorized access attempt to chat: {room_id}")
        session.pop('last_visit', None)
        return redirect(url_for("min.onboard"))

    # Render template
    response = make_response(render_template('user/min-index.html', chat=chat, username=user.name))
    
    # Prevent caching to avoid old room_id issues
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response


@min_bp.route('/chat/<room_id>/ping_admin', methods=['POST', 'GET'])
@login_required
def ping_admin(room_id):
    if request.method == "GET":
        return redirect(f'/chat/{room_id}')

    # Get admin settings from current admin in session
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get('admin_id'))

    # Use admin's settings if available, otherwise fall back to default
    if current_admin:
        settings = current_admin.settings
        timings = settings.get('timings', [])
        timezone = settings.get('timezone', "UTC")
    else:
        # Fallback for superadmin or default settings
        settings = current_app.config.get('SETTINGS', {})
        timings = settings.get('timings', [])
        timezone = settings.get('timezone', "UTC")

    now = UTCZoneManager().get_current_date(timezone)
    current_day = now.strftime('%A').lower()
    current_time = now.strftime('%H:%M')

    available = any(
        t['day'].lower() == current_day and t['startTime'] <= current_time <= t['endTime']
        for t in timings
    )

    # Proceed with ping logic
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(session['user_id'])
    
    chat = chat_service.get_chat_by_room_id(room_id)

    if not chat:
        if request.headers.get('HX-Request'):
            return "Chat not found", 404
        return jsonify({"error": "Chat not found"}), 404

    if chat.admin_required:
        return "", 304

    chat_service.set_admin_required(chat.room_id, True)

    current_app.socketio.emit('admin_required', {
        'room_id': room_id,
        'chat_id': chat.chat_id,
        'subject': chat.subject
    }, room='admin')

    noti_service = NotificationService(current_app.db)
    noti_service.create_admin_required_notification(
        chat.admin_id, chat.room_id, user.name)

    new_message = chat_service.add_message(
        chat.room_id, 'SYSTEM', 'Ana has been notified! She will join soon'
    )
    current_app.socketio.emit('new_message', {
        'sender': 'SYSTEM',
        'content': new_message.content,
        "html": render_template("/user/fragments/chat_message.html", message=new_message, username=user.name),
        'timestamp': new_message.timestamp.isoformat(),
        'room_id': room_id
    }, room=room_id)

    msg = f"""Hi Ana,

{user.name} has just requested to have a live chat. If you'd like to start the conversation, simply click the link below:

{current_app.config['SETTINGS']['backend_url']}/admin/chat/{chat.room_id}

User Information:
    Name: {user.name}
    Email: {user.email}
    Phone #: {user.phone}
    Designation: {user.desg}
    IP: {user.ip}
    Country: {user.country}
    City: {user.city}
    Last messages: {[f'{m.sender}: {m.content}' for m in chat.messages[-5:-1]]}
    \n\n
Auto Generated Message"""

    mail = Mail(current_app)
    status = send_email(current_admin.email, f'Assistance Required: {chat.subject}', 
               "Ping", mail, render_template('/email/admin_required.html', user=user, chat=chat))

    noti_res = send_push_noti(
        admin_service.get_expo_tokens(session.get("admin_id")), 
        "Admin Assistance Required!", 
        f'{user.name}: {chat.subject}', 
        chat.room_id
    )
    
    if noti_res.status_code != 200:
        print(f"Notification Error: {noti_res.__dict__}")

    if request.headers.get('HX-Request'):
        return "", 204

    return jsonify({"status": "Ana has been notified"}), 200


import wave

def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


@min_bp.route('/chat/<room_id>/send_audio', methods=['POST','GET'])
@login_required
def receive_audio_blob(room_id):
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    audio_bytes = audio_file.read()
    
    print(f"Received audio: {len(audio_bytes)} bytes")
    
    # RESET FILE POINTER to beginning so we can save it
    audio_file.seek(0)
    
    try:
        resp = current_app.bot.transcribe(audio_bytes)
        print(resp)
    except Exception as e:
        print(f"Transcription error: {e}")
        return jsonify({'error': 'Transcription failed'}), 500

    print(session.get('admin_id'))
    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(session['user_id'])
    chat_service = ChatService(current_app.db)
    admin = AdminService(current_app.db).get_admin_by_id(
        session.get('admin_id'))

    chat = chat_service.get_chat_by_room_id(room_id)
    print(chat)
    if not chat:
        if request.headers.get('HX-Request'):
            return "Chat not found", 404
        return jsonify({"error": "Chat not found"}), 404
    print(resp)

    new_message = chat_service.add_message(chat.room_id, user.name, resp, type="audio")

    save_path = os.path.join('files', f"{chat.room_id}", f"{new_message.id}.wav")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # Now this will work since we reset the file pointer
    audio_file.save(save_path) 

    current_app.socketio.emit('new_message', {
        'sender': user.name,
        'content': resp,
        'timestamp': new_message.timestamp.isoformat(),
        'room_id': chat.room_id,
        'type': "audio",
        "id": str(new_message.id)
    }, room=chat.room_id)
    
    if not chat.admin_required:
        try:
            msg, usage = current_app.bot.respond(
                f"Subject of chat: {chat.subject}\n{resp}", chat.room_id)
            print(msg)
            audio = current_app.bot.generate_audio(msg)

            bot_message = chat_service.add_message(chat.room_id, "bot", msg, type="audio")

            current_app.socketio.emit('new_message', {
                'sender': "bot",
                'content': msg,
                'timestamp': bot_message.timestamp.isoformat(),
                'room_id': chat.room_id,
                'type': "audio",
                "id": str(bot_message.id)
            }, room=chat.room_id)

            save_path = os.path.join('files', f"{chat.room_id}", f"{bot_message.id}.wav")
            wave_file(save_path, audio)
        except Exception as e:
            print(f"Bot response error: {e}")

    return "", 200


from flask import send_from_directory, abort

@min_bp.route("/chat/<room_id>/audio_file/<message_id>")
@login_required
def audio_file(room_id, message_id):
    print(room_id)
    # Directory where audio files for this chat are stored
    base_dir = os.path.join('files', room_id)
    
    # Construct full file path
    file_path = os.path.join(base_dir, f"{message_id}.wav")
    print(file_path)
    
    # Make sure the file exists
    if not os.path.exists(file_path):
        abort(404, description="Audio file not found")
    
    # Serve the file safely
    return send_from_directory(base_dir, f"{message_id}.wav", mimetype="audio/wav")


@min_bp.route('/chat/<room_id>/send_message', methods=['POST', 'GET'])
@login_required
def send_message(room_id):
    if request.method == "GET":
        return redirect(f'/chat/{room_id}')
        
    message = request.form.get('message')
    if not message or not len(message):
        return "", 302

    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(session['user_id'])
    chat_service = ChatService(current_app.db)
    admin = AdminService(current_app.db).get_admin_by_id(
        session.get('admin_id'))

    chat = chat_service.get_chat_by_room_id(room_id)
    print(chat)
    
    if not chat:
        print(f"Chat not found for room_id: {room_id}")
        return jsonify({"error": "Chat not found"}), 404
    
    # Security check - verify this chat belongs to the current user
    if not chat.room_id.startswith(user.user_id):
        print(f"Unauthorized: User {user.user_id} tried to send to chat {room_id}")
        return jsonify({"error": "Unauthorized"}), 403

    new_message = chat_service.add_message(
        chat.room_id, user.name, message)

    new_message.content = markdown.markdown(new_message.content)
    
    current_app.socketio.emit('new_message', {
        'sender': user.name,
        'content': message,
        'timestamp': new_message.timestamp.isoformat(),
        'room_id': chat.room_id,
        "html": render_template("/user/fragments/chat_message.html", message=new_message, username=user.name)
    }, room=chat.room_id)

    print('hello')
    print(len(chat.messages))

    admin_service = AdminService(current_app.db)
    noti_res = send_push_noti(admin_service.get_expo_tokens(
        session.get("admin_id")), "New Message", f'{user.name}: {message}', chat.room_id)
    print(f"Noti done: {noti_res}")
    if noti_res.status_code != 200:
        print(f"Notification Error: {noti_res.__dict__}")

    if not chat.admin_required:
        try:
            msg, usage = current_app.bot.respond(
                f"Subject of chat: {chat.subject}\n{message}", chat.room_id)
            admin_service = AdminService(current_app.db).update_tokens(
                admin.admin_id, usage['cost'])

            usage_service = UsageService(current_app.db)
            usage_service.add_cost(session.get("admin_id"),
                                   usage['input'], usage['output'], usage['cost'])
            bot_message = chat_service.add_message(
                chat.room_id, chat.bot_name, msg)

            current_app.socketio.emit('new_message', {
                "html": render_template("/user/fragments/chat_message.html", message=bot_message, username=user.name),
                'room_id': chat.room_id,
                'sender': chat.bot_name,
                'content': msg,
                'timestamp': bot_message.timestamp.isoformat()
            }, room=chat.room_id)
        except Exception as e:
            print(f"Bot response error: {e}")
    else:
        current_app.socketio.emit('new_message_admin', {
            "html": render_template("/user/fragments/chat_message.html", message=new_message, username=user.name),
            'room_id': chat.room_id,
            'sender': user.name,
            'content': message,
            'timestamp': new_message.timestamp.isoformat(),
        }, room=chat.room_id)
        noti_service = NotificationService(current_app.db)
        noti_service.create_notification(chat.admin_id, f'{
                                         user.name} sent a message', message, 'admin_required', chat.room_id)

    return jsonify({'success': True}), 200


def register_min_socketio_events(socketio):
    @socketio.on('join_min')
    def on_join(data):
        room = data.get('room')

        # Allow joining only if authenticated
        if 'user_id' not in session:
            return

        join_room(room)
        username = session.get('name', "USER")
        current_app.config['ONLINE_USERS'] += 1
        emit('status', {'msg': f'{username} has joined the room.'}, room=room)

    @socketio.on('leave_min')
    def on_leave(data):
        room = data.get('room')
        user_id = session.get('user_id')

        if not room or not user_id:
            return

        user_service = UserService(current_app.db)
        user = user_service.get_user_by_id(user_id)
        if not user:
            return

        leave_room(room)

        # FIX: Decrement, not increment!
        current_app.config['ONLINE_USERS'] = max(0, current_app.config.get('ONLINE_USERS', 1) - 1)
        emit('status', {'msg': f'{user.name} has left the room.'}, room=room)
