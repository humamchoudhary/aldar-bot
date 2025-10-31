from services.whatsapp_service import WhatsappService
from services.call_service import CallService
from services.notification_service import NotificationService
from flask_mail import Mail
from flask import request, flash, make_response, send_file
import zipfile
import io
import json
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta
from collections import Counter
from services.timezone import UTCZoneManager
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import logging
# from # p# # print import p# print
from services.usage_service import UsageService
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import requests
from .scrape import scrape_web
import re
from flask import send_from_directory
import uuid
import os
from flask import (
    render_template,
    session,
    request,
    jsonify,
    redirect,
    url_for,
    current_app,
    flash,
)
from flask_socketio import join_room, emit
from functools import wraps
from . import admin_bp
from services.chat_service import ChatService
from services.user_service import UserService
from werkzeug.utils import secure_filename
import pdf2image
from services.logs_service import LogsService
from models.log import LogLevel, LogTag
from services.admin_service import AdminService
from services.email_service import send_email
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import calendar
from functools import lru_cache

UPLOAD_FOLDER = os.path.join(os.getcwd(), "user_data")


logger = logging.getLogger(__name__)


def admin_required(_func=None, *, roles=None):
    if roles is None:
        roles = ["admin", "superadmin"]
    elif isinstance(roles, str):
        roles = [roles]

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("role") not in roles:

                return redirect(url_for("admin.login"))

            if not session.get("admin_id"):
                session["next"] = request.path
                return redirect(url_for("admin.login"))

            admin_service = AdminService(current_app.db)
            current_admin = admin_service.get_admin_by_id(session["admin_id"])

            if not current_admin or not current_admin.has_permission(roles):
                return redirect(url_for("admin.login"))

            from flask import g

            g.current_admin = current_admin

            return f(*args, **kwargs)

        return decorated_function

    if _func:
        return decorator(_func)

    return decorator


@admin_bp.route("/pricing/")
@admin_required
def pricing_page():
    return render_template("admin/pricing.html")


@admin_bp.route("/faq/")
@admin_required
def faq_page():
    return render_template("admin/faq.html")


@admin_bp.route("/change-logs")
@admin_required
def changelogs_page():
    return render_template("admin/change-logs.html")


@admin_bp.route("/logs/")
@admin_required
def view_logs():
    """Main logs page"""
    admin = AdminService(current_app.db).get_admin_by_id(
        session.get("admin_id"))
    logs_service = LogsService(current_app.db)

    # Regular admins only see their own logs
    admin_filter = session.get(
        "admin_id") if admin.role != "superadmin" else None
    logs = logs_service.get_recent_logs(admin_filter, 1000)

    return render_template("admin/logs.html", logs=logs, selected_log=None)


@admin_bp.route("/logs/filter")
@admin_required
def filter_logs():
    """Filter logs with HTMX"""
    admin = AdminService(current_app.db).get_admin_by_id(
        session.get("admin_id"))
    logs_service = LogsService(current_app.db)

    # Get filter parameters
    levels = request.args.getlist("level")
    tags = request.args.getlist("tag")
    user_id = request.args.get("user_id", "").strip()
    admin_id = admin.admin_id
    message_search = request.args.get("message_search", "").strip()
    sort_order = request.args.get("sort", "timestamp_desc")
    limit = request.args.get("limit", 1000)

    # Parse dates
    start_date = end_date = None
    try:
        start_date = (
            datetime.fromisoformat(request.args.get("start_date", ""))
            if request.args.get("start_date")
            else None
        )
        end_date = (
            datetime.fromisoformat(request.args.get("end_date", ""))
            if request.args.get("end_date")
            else None
        )
    except ValueError:
        pass

    # Convert to enums
    level_enums = [LogLevel(level) for level in levels if level]
    tag_enums = [LogTag(tag) for tag in tags if tag]

    # Regular admins can't filter by other admin_ids
    current_admin_id = session.get(
        "admin_id") if admin.role != "superadmin" else None
    # printmessage_search)
    logs = logs_service.search_logs_advanced(
        levels=level_enums or None,
        tags=tag_enums or None,
        user_id=user_id or None,
        admin_id=admin_id or None,
        message_search=message_search or None,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        current_admin_id=current_admin_id,
    )

    # Apply sorting
    if sort_order == "timestamp_asc":
        logs.sort(key=lambda x: x.timestamp)
    elif sort_order in ("level_desc", "level_asc"):
        level_priority = {
            LogLevel.CRITICAL: 5,
            LogLevel.ERROR: 4,
            LogLevel.WARNING: 3,
            LogLevel.INFO: 2,
            LogLevel.DEBUG: 1,
        }
        reverse = sort_order == "level_desc"
        logs.sort(key=lambda x: level_priority.get(
            x.level, 0), reverse=reverse)

    return render_template("admin/logs_table.html", logs=logs)


@admin_bp.route("/log/<string:log_id>")
@admin_required
def view_log_detail(log_id):
    """View individual log details"""
    admin = AdminService(current_app.db).get_admin_by_id(
        session.get("admin_id"))
    logs_service = LogsService(current_app.db)

    log = logs_service.get_log_by_id(log_id)
    if not log:
        if request.headers.get("HX-Request") == "true":
            return '<div class="p-4 text-red-500">Log not found</div>', 404
        return "Log not found", 404

    # Check access for regular admins
    if admin.role != "superadmin" and log.admin_id != session.get("admin_id"):
        if request.headers.get("HX-Request") == "true":
            return '<div class="p-4 text-red-500">Access denied</div>', 403
        return "Access denied", 403

    if request.headers.get("HX-Request") == "true":
        return render_template("admin/log_detail.html", log=log)
    else:
        admin_filter = session.get(
            "admin_id") if admin.role != "superadmin" else None
        logs = logs_service.get_recent_logs(admin_filter, limit=10000)
        return render_template("admin/logs.html", logs=logs, selected_log=log)


@admin_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("admin/forgot_password.html")

    data = request.json
    username = data.get("username")
    email = data.get("email")

    if not username or not email:
        return jsonify({"error": "Username and email are required"}), 400

    admin_service = AdminService(current_app.db)
    admin = admin_service.get_admin_by_username(username)

    if not admin or admin.email != email:
        return jsonify({"error": "No account found with that username and email"}), 404

    # Create reset token
    token = admin_service.create_password_reset_token(admin.admin_id)

    # Send email with reset link
    reset_url = url_for("admin.reset_password", token=token, _external=True)
    mail = Mail(current_app)
    try:
        # msg = Message(
        #     subject="Password Reset Request",
        #     recipients=[admin.email],
        #     html=render_template('admin/email/reset_password.html',
        #                          reset_url=reset_url,
        #                          admin=admin)
        # )
        # mail.send(msg)

        status = send_email(
            admin.email,
            "GoBot Password Reset",
            f"""<!DOCTYPE html>
                            Hello {admin.username},
                            You have requested to reset your password. Please click the link below to reset your password:\n
                            {reset_url}\n
                            This link will expire in 1 hour.
                            If you didn't request this, please ignore this email.
                                """,
            mail=mail,
            html_message=render_template(
                "/email/forget_pass.html", admin=admin, reset_url=reset_url
            ),
        )

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Password reset link sent to your email",
                }
            ),
            200,
        )
    except Exception as e:
        current_app.logger.error(
            f"Failed to send password reset email: {str(e)}")
        return jsonify({"error": "Failed to send password reset email"}), 500


@admin_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    admin_service = AdminService(current_app.db)
    admin = admin_service.validate_password_reset_token(token)

    if not admin:
        return render_template("admin/reset_password_invalid.html")

    if request.method == "GET":
        return render_template("admin/reset_password_form.html", token=token)

    # Handle POST request for password reset
    data = request.json
    # # printdata)
    new_password = data.get("password")
    confirm_password = data.get("confirm_password")
    # # # printdict(request.form))
    # # printnew_password)
    # # printconfirm_password)

    if not new_password or not confirm_password:
        return jsonify({"error": "Both password fields are required"}), 400

    if new_password != confirm_password:
        return jsonify({"error": "Passwords do not match"}), 400

    # Update password and clear token
    admin_service.update_admin_password(admin.admin_id, new_password)
    admin_service.clear_password_reset_token(admin.admin_id)

    return (
        jsonify(
            {
                "status": "success",
                "message": "Password updated successfully",
                "redirect": url_for("admin.login"),
            }
        ),
        200,
    )




@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("admin/login.html")

    data = request.json
    username = data.get("username")
    password = data.get("password")
    ip_address = request.headers.get(
        "X_Real-IP", request.remote_addr).split(",")[0]

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    admin_service = AdminService(current_app.db)
    admin = admin_service.authenticate_admin(username, password)

    if not admin:
        return jsonify({"error": "Invalid credentials"}), 401

    if not admin.two_fa:
        # No 2FA required, complete login
        return complete_admin_login(admin)
    # Check if IP is trusted (completed 2FA within last 30 mins)
    if admin_service.is_ip_trusted(admin.admin_id, ip_address,current_app.config['SETTINGS'].get('2fa')):
        # IP is trusted, proceed with login
        return complete_admin_login(admin)

    # IP not trusted, require 2FA
    token_info = admin_service.create_2fa_token(admin.admin_id, ip_address,current_app.config['SETTINGS'].get('2fa'))
    if not token_info:
        return (
            jsonify({"error": "Failed to create 2FA token", "requires_2fa": True}),
            500,
        )
    mail = Mail(current_app)
    # # printf"TEMP 2FA CODE: {token_info['code']}")
    # Send the 2FA code via email
    status = send_email(
        admin.email,
        "Your GoGlobe 2FA Verification Code",
        f"""<!DOCTYPE html>
        <html>
        <body>
            <p>Hello {admin.username},</p>
            <p>Your verification code is: <strong>{token_info['code']}</strong></p>
            <p>This code will expire in 10 minutes.</p>
            <p>If you didn't request this, please secure your account immediately.</p>
        </body>
        </html>
        """,
        mail=mail,
        html_message=render_template(
            "/email/2fa_code.html",
            admin=admin,
            code=token_info["code"],
            expires_at=token_info["expires_at"],
        ),
    )

    if not status:
        return jsonify({"error": "Failed to send 2FA code"}), 500

    return (
        jsonify(
            {
                "status": "2fa_required",
                "message": "2FA code sent to your email",
                "admin_id": admin.admin_id,
            }
        ),
        200,
    )


def complete_admin_login(admin):
    """Common login completion logic"""
    # Clear session and set admin session
    next_url = session.pop("next", None)
    session.clear()
    session["admin_id"] = admin.admin_id
    session["role"] = admin.role
    session["username"] = admin.username

    if next_url:
        return jsonify({"status": "success", "redirect": next_url}), 200
    return jsonify({"status": "success", "redirect": url_for("admin.index")}), 200


@admin_bp.route("/verify-2fa", methods=["POST"])
def verify_2fa():
    data = request.json
    admin_id = data.get("admin_id")
    code = data.get("code")
    ip_address = request.headers.get(
        "X_Real-IP", request.remote_addr).split(",")[0]

    if not admin_id or not code:
        return jsonify({"error": "Admin ID and code are required"}), 400

    admin_service = AdminService(current_app.db)
    verification = admin_service.verify_2fa_code(admin_id, ip_address, code)

    if not verification.get("success"):
        return jsonify({"error": verification.get("error")}), 401

    # 2FA verified successfully - mark IP as trusted
    admin_service.add_trusted_ip(admin_id, ip_address)

    admin = admin_service.get_admin_by_id(admin_id)
    if not admin:
        return jsonify({"error": "Admin not found"}), 404

    return complete_admin_login(admin)


@admin_bp.route("/onboarding", methods=["GET", "POST"])
@admin_required
def onboard():
    if request.method == "GET":
        return render_template("admin/onboarding.html")
    else:
        data = request.json
        # # printdata)
        admin_id = session.get("admin_id")
        admin_service = AdminService(current_app.db)
        admin_service.update_admin_login(
            admin_id, data["username"], data["password"], data["email"], data["phone"]
        )

        return jsonify({"message": "No Error"})


@admin_bp.route("/chat/<room_id>", methods=["GET"])
@admin_required
def chat(room_id):
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    chat = chat_service.get_chat_by_room_id(room_id)
    if not chat:
        return redirect(url_for("admin.get_all_chats"))
    # Get initial chats with pagination
    chats = chat_service.get_chats_with_limited_messages(
        admin_id=session.get("admin_id"),
        limit=20,
        skip=0
    )
    # Prepare chat data with usernames
    user = user_service.get_user_by_id(chat.user_id)
    chat_service.set_chat_viewed(chat.room_id)
    chat_counts = chat_service.get_chat_counts_by_filter(session.get("admin_id"))
    if request.headers.get("HX-Request"):
        return render_template(
            "components/chat-area.html", 
            chat=chat, 
            user=user, 
            username="Ana",
            chat_counts=chat_counts,
        # has_more=len(chats_data) == 20,
        )
    # chats_data = []
    # for c in chats:
    #     data = c.to_dict()
    #     data["username"] = user_service.get_user_by_id(c.user_id).name
    #     chats_data.append(data)
    # chats_data.sort(key=lambda x: x["updated_at"], reverse=True)
    # chats_data.sort(key=lambda x: x["updated_at"], reverse=True)
    return render_template(
        "admin/chats.html", 
        chat=chat, 
        # chats=chats_data, 
        user=user, 
        username="Ana",

        has_more=len(chats) == 20,
            chat_counts=chat_counts,next_page=1
    )

from pprint import pprint

@admin_bp.route('/chats_list/')
@admin_required
def get_chat_list():
    page = request.args.get('page', 0, type=int)
    limit = request.args.get('limit', 20, type=int)
    filter_type = request.args.get('filter', 'all')
    
    room_id = None
    if request.referrer:
        room_id = request.referrer.split("/")[-1]
    
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    
    # Get chats based on filter with pagination
    chats = chat_service.get_filtered_chats_paginated(
        admin_id=session.get("admin_id"),
        filter_type=filter_type,
        limit=limit,
        skip=page * limit
    )
    
    # Prepare chat data with usernames
    chats_data = []
    for c in chats:
        data = c.to_dict()
        data["username"] = user_service.get_user_by_id(c.user_id).name
        chats_data.append(data)
    chats_data.sort(key=lambda x: x["updated_at"], reverse=True)
    cchat = chat_service.get_chat_by_room_id(room_id) if room_id else None
    
    # Check if this is a pagination request
    is_pagination = request.args.get('pagination') == 'true'
    if is_pagination:
        # Return only the chat items for infinite scroll
        return render_template(
            "components/chat-items-only.html", 
            chats=chats_data, 
            cur_chat=cchat,
        )
    return render_template(
        "components/chat-list.html", 
        chats=chats_data, 
        cur_chat=cchat,
        has_more=len(chats_data) == limit,
        next_page=page + 1,
    )


@admin_bp.route("/search/", methods=["POST"])
@admin_required
def search():
    query = request.form.get("search-q").lower()
    if not query:
        return render_template("components/search-results.html", search_chats=[])

    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    chats = chat_service.get_all_chats(session.get("admin_id"))

    search_chats = set()
    for chat in chats:
        user = user_service.get_user_by_id(chat.user_id)
        if not user:
            continue

        chat.username = user.name

        # Match against user fields
        if (
            query in user.name.lower() or
            (user.country and query in user.country.lower()) or
            (user.city and query in user.city.lower())
        ):
            search_chats.add(chat)
            continue

        # Match against messages
        if any(query in message.content.lower() for message in chat.messages):
            search_chats.add(chat)

    return render_template(
        "components/search-results.html",
        search_chats=list(search_chats)
    )


@admin_bp.route("/chat/<room_id>/user")
def chat_user(room_id):
    chat_service = ChatService(current_app.db)

    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(
        chat_service.get_chat_by_room_id(room_id).user_id
    )

    return render_template("admin/user.html", user=user.to_dict())


@admin_bp.route("/chat/min/<room_id>", methods=["GET"])
@admin_required
def chat_mini(room_id):

    chat_service = ChatService(current_app.db)

    chat = chat_service.get_chat_by_room_id(room_id)
    return render_template("admin/fragments/chat_mini.html", chat=chat, username="Ana")


@admin_bp.route("/user/<string:user_id>/details", methods=["GET"])
@admin_required
def get_user_details(user_id):

    user_service = UserService(current_app.db)
    user = user_service.get_user_by_id(user_id)
    if request.headers.get("HX-Request"):
        return render_template("components/chat-user-info.html", user=user)

    return jsonify(user.to_dict())


@admin_bp.route("/chats/<string:filter>", methods=["GET"])
@admin_required
def filter_chats(filter):
    page = request.args.get('page', 0, type=int)
    limit = request.args.get('limit', 20, type=int)
    is_pagination = request.args.get('pagination') == 'true'

    # Validate and sanitize inputs
    limit = min(max(limit, 1), 100)  # Limit between 1-100
    page = max(page, 0)  # Ensure non-negative page
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    
    # Get filtered chats with pagination
    chats = chat_service.get_filtered_chats_paginated(
        admin_id=session.get("admin_id"),
        filter_type=filter,
        limit=limit,
        skip=page * limit
    )
    
    # Batch fetch users to reduce individual queries
    user_ids = [c.user_id for c in chats]
    users_dict = user_service.get_users_by_ids(user_ids)  # Single query for all users
    # # printusers_dict)
    
    # Build chat data with usernames
    chats_data = [
        {**chat.to_dict(), "username": users_dict[chat.user_id]['name']}
        for chat in chats
    ]

    chats_data.sort(key=lambda x: x['updated_at'], reverse=True)
    
    # Determine template based on request type
    template = (
        "components/chat-items-only.html" if is_pagination 
        else "components/chat-list.html"
    )
    
    # Build context conditionally
    context = {"chats": chats_data}

    if not is_pagination:
        context.update({
            "has_more": len(chats_data) == limit,
            "next_page": page + 1,
            "current_filter": filter
        })
    # p# printchats_data)    
    return render_template(template, **context)

import json
def get_country_id(file_path, target_country):
    with open(file_path, 'r') as f:
        data = json.load(f)
    for entry in data:
        # printentry.get('short_name'))
        if entry.get('short_name',"").lower() == target_country.lower():
            return entry.get('country_id')
    return None 

@admin_bp.route("/chat/<room_id>/export", methods=["POST"])
@admin_required
def export_chat(room_id):
    chat_service = ChatService(current_app.db)
    chat = chat_service.get_chat_by_room_id(room_id)

    if chat:
        user_service = UserService(current_app.db)
        user = user_service.get_user_by_id(chat.user_id)
        # try:
        erp_url = os.environ.get("ERP_URL")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "authtoken": f"{os.environ.get('ERP_TOKEN')}",
        }
        # printuser.country)
        # printget_country_id('tblcountries.json',user.country))
        data = {
            "name": user.name,
            "company": user.company,
            "title": user.desg,
            "phonenumber": user.phone,
            "email": f"{user.email}",
            "city":str(user.city),
            "state":str(user.city),
            "country":int(get_country_id('tblcountries.json',user.country)),
            "description":"\n".join(
                [
                    f"{message.sender.lower()}: {message.content[:15] + ('...' if len(message.content) > 15 else '')}"
                    if message.sender.lower() == "bot"
                    else f"{message.sender}: {message.content}"
                    for message in chat.messages
                ]
                ),
            "status":2,"hash":"null"
        }

        r = requests.post(erp_url, headers=headers, data=data)
        # printf"DATA: {data}")
        # printr)
        if r.status_code == 200:

            data = r.json()
            if not chat_service.export_chat(room_id, data.get("lead_id", None)):
                return "Error in exporting: Chat not found", 404
        elif r.status_code==404:
            if not chat_service.export_chat(room_id, None):
                return "Error in exporting: Chat not found", 404
            return f"Error from ERP: {r.status_code}, {r.json().get('message','Internal Server error').replace('<p>',"").replace('</p>',"")}",202

        else:
            # # printr.json())
            return f"Error from ERP: {r.status_code}, {r.json().get('message','Internal Server error').replace('<p>',"").replace('</p>',"")}",500
        return "success", 200

    return "Chat not found", 404


@admin_bp.route("/chat/<room_id>/archive", methods=["POST"])
@admin_required
def archive_chat(room_id):
    chat_service = ChatService(current_app.db)
    chat = chat_service.get_chat_by_room_id(room_id)

    if chat:
        if not chat_service.archive_chat(room_id):
            return "Error in exporting: Chat not found", 404

        return "success", 200

    return "Chat not found", 404



@admin_bp.route('/chat-counts')
@admin_required
def chat_couts():
    chat_service = ChatService(current_app.db)
    return jsonify(
            chat_service.get_chat_counts_by_filter(session.get('admin_id')))

@admin_bp.route("/chat/<room_id>/intervene",methods=["POST"])
@admin_required
def intervene(room_id):
    admin_service = AdminService(current_app.db)
    chat_service = ChatService(current_app.db)
    chat_service.set_admin_required(room_id,True)
    return "",200


@admin_bp.route('/chat/<chat_id>/send_audio', methods=['POST'])
@admin_required
def receive_audio_blob(chat_id):
        if 'audio' not in request.files:
            if request.headers.get('HX-Request'):
                return "No audio file provided", 400
            return jsonify({'error': 'No audio file provided'}), 400

        audio_file = request.files['audio']
        audio_bytes = audio_file.read()  # Get bytes from file
        
        # printf"Received audio: {len(audio_bytes)} bytes")
        
        # RESET FILE POINTER to beginning so we can save it
        audio_file.seek(0)
        
        # Transcribe audio
        resp = current_app.bot.transcribe(audio_bytes)
        # printresp)

        # Get admin info from session
        admin_service = AdminService(current_app.db)
        admin = admin_service.get_admin_by_id(session.get('admin_id'))
        
        if not admin:
            if request.headers.get('HX-Request'):
                return "Admin not found", 404
            return jsonify({"error": "Admin not found"}), 404

        chat_service = ChatService(current_app.db)
        
        # Get chat by room_id (using the provided chat_id directly as it should be room_id)
        chat = chat_service.get_chat_by_room_id(chat_id)
        if not chat:
            if request.headers.get('HX-Request'):
                return "Chat not found", 404
            return jsonify({"error": "Chat not found"}), 404

        # printf"Transcription: {resp}")

        # Add message as admin (using admin name instead of user name)
        new_message = chat_service.add_message(chat.room_id, admin.username, resp, type="audio")

        # Save audio file
        save_path = os.path.join('files', f"{chat.room_id}", f"{new_message.id}.wav")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # Now this will work since we reset the file pointer
        audio_file.save(save_path) 

        # Emit socket event
        current_app.socketio.emit('new_message', {
            'sender': admin.username,
            'content': resp,
            'timestamp': new_message.timestamp.isoformat(),
            'room_id': chat.room_id,
            'type': "audio",
            "id": str(new_message.id)
        }, room=chat.room_id)
        
        
        if request.headers.get('HX-Request'):
            return "", 200
        return jsonify({"success": True}), 200
        



from flask import send_from_directory, abort
import os


@admin_bp.route("/chat/<chat_id>/audio_file/<message_id>")
@admin_required
def audio_file(chat_id, message_id):
    base_dir = os.path.join('files', chat_id) 
    file_path = os.path.join(base_dir, f"{message_id}.wav")
    if not os.path.exists(file_path):
        abort(404, description="Audio file not found")
    return send_from_directory(base_dir, f"{message_id}.wav", mimetype="audio/wav")




@admin_bp.route("/chat/<room_id>/send_message", methods=["POST"])
@admin_required
def send_message(room_id):
    try:
        # if 'user_id' not in session:
        #     if request.headers.get('HX-Request'):
        #         return "Please log in first", 401
        #     return "<h1>Unauthorized</h1>", 401

        message = request.form.get("message")
        # # # printrf'{message}')
        # # # printf'{room_id}')
        if not message:
            return "", 302
        chat_service = ChatService(current_app.db)
        user_service = UserService(current_app.db)

        chat = chat_service.get_chat_by_room_id(room_id)
        if not chat:
            if request.headers.get("HX-Request"):
                return "Chat not found", 404
            return jsonify({"error": "Chat not found"}), 404

        new_message = chat_service.add_message(chat.room_id, "Ana", message)
        user = user_service.get_user_by_id(chat.user_id)
        if not user:
            return "<p>User Not Found</>"
        current_app.socketio.emit(
            "new_message",
            {

                'room_id': chat.room_id,
                "sender": new_message.sender,
                "content": message,
                "timestamp": new_message.timestamp.isoformat(),
            },
            room=room_id,
        )

        # return render_template('admin/fragments/chat_message.html', message=new_message, username="Ana")
        return "", 200
    except Exception as e:
        return f"{e}", 500
        # # # printe)


@admin_bp.route("/files/")
@admin_required
def files():
    admin_id = session.get("admin_id")
    path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
    os.makedirs(path, exist_ok=True)
    return render_template("admin/files.html", files=sorted(os.listdir(path)))


def is_readable_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


@admin_bp.route("/files/<file_name>", methods=["GET"])
@admin_required
def file_page(file_name):
    file = {}
    file_readable = False

    admin_id = session.get("admin_id")
    path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
    file_path = os.path.join(path, file_name)
    if os.path.exists(file_path):
        file["filename"] = file_name
        # Get file extension
        file_ext = os.path.splitext(file_name)[1].lower()
        # Check if file is an image
        if file_ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
            # If it's an image, we don't need to read its content
            # The template will display it as an image
            file_readable = False
        else:
            # Try to read the file content for non-image files
            file["content"] = is_readable_file(file_path)
            if file["content"]:
                file_readable = True
    return render_template(
        "admin/read_file.html", file=file, file_readable=file_readable
    )


@admin_bp.route("/files/delete/<file_name>", methods=["POST"])
@admin_required
def delete_file(file_name):

    admin_id = session.get("admin_id")
    path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
    try:
        file_path = os.path.join(path, file_name)
        # Check if file exists before attempting to delete
        if os.path.exists(file_path):
            os.remove(file_path)
            flash("File deleted successfully", "success")
        else:
            flash("File not found", "error")
    except Exception as e:
        flash(f"Error deleting file: {str(e)}", "error")

    # Redirect to the file list page
    # Assuming 'file_list' is your route for /file
    return redirect(url_for("admin.files"))


@admin_bp.route("/serve-file/<file_name>")
@admin_required
def serve_file(file_name):

    admin_id = session.get("admin_id")
    path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
    # Securely serve the file from the UPLOAD_FOLDER
    return send_from_directory(path, file_name)


import pdfplumber
# @admin_bp.route("/upload", methods=["POST"])
# @admin_required
# def upload_file():
#     if "files" not in request.files:
#         return jsonify({"error": "No files provided"}), 400
#
#     uploaded_files = request.files.getlist("files")  # Get multiple files
#     file_items = []
#
#     for file in uploaded_files:
#         if file.filename == "":
#             continue
#
#         original_filename = secure_filename(file.filename)
#         base_filename = os.path.splitext(original_filename)[0]
#         file_extension = os.path.splitext(original_filename)[1].lower()
#         unique_filename = f"{uuid.uuid4().hex}{file_extension}"
#
#         admin_id = session.get("admin_id")
#         path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
#         file_path = os.path.join(path, unique_filename)
#
#     if file_extension == ".pdf":
#         try:
#             temp_path = os.path.join(path, f"temp_{unique_filename}")
#             file.save(temp_path)
#
#             text = ""
#             with pdfplumber.open(temp_path) as pdf:
#                 for page in pdf.pages:
#                     page_text = page.extract_text()
#                     if page_text:
#                         text += page_text + "\n"
#
#             os.remove(temp_path)
#
#             if text.strip():
#                 # Save extracted text as .txt file
#                 text_filename = f"{base_filename}.txt"
#                 text_path = os.path.join(path, text_filename)
#                 with open(text_path, "w", encoding="utf-8") as f:
#                     f.write(text)
#
#                 file_items.append(
#                     render_template("components/file_item.html", file=text_filename)
#                 )
#             else:
#                 # If no text extracted, fall back to saving the PDF as is
#                 file.save(file_path)
#                 file_items.append(
#                     render_template("components/file_item.html", file=unique_filename)
#                 )
#
#         except Exception as e:
#             file.seek(0)
#             file.save(file_path)
#             # printf"PDF text extraction error: {e}")
#             file_items.append(
#                 render_template("components/file_item.html", file=unique_filename)
#             )
#     else:
#         file.save(file_path)
#         file_items.append(
#             render_template("components/file_item.html", file=unique_filename)
#         )
#
#     return "".join(file_items), 200  # Return all file items as HTML


@admin_bp.route("/upload", methods=["POST"])
@admin_required
def upload_file():
    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400
    uploaded_files = request.files.getlist("files")  # Get multiple files
    file_items = []
    for file in uploaded_files:
        if file.filename == "":
            continue
        original_filename = secure_filename(file.filename)
        base_filename = os.path.splitext(original_filename)[0]
        file_extension = os.path.splitext(original_filename)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        admin_id = session.get("admin_id")
        path = os.path.join(UPLOAD_FOLDER, f"{admin_id}", "files")
        file_path = os.path.join(path, unique_filename)
        
        if file_extension == ".pdf":
            try:
                temp_path = os.path.join(path, f"temp_{unique_filename}")
                file.save(temp_path)
                text = ""
                with pdfplumber.open(temp_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                os.remove(temp_path)
                if text.strip():
                    # Save extracted text as .txt file
                    text_filename = f"{base_filename}.txt"
                    text_path = os.path.join(path, text_filename)
                    with open(text_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    file_items.append(
                        render_template("components/file_item.html", file=text_filename)
                    )
                else:
                    # If no text extracted, fall back to saving the PDF as is
                    file.save(file_path)
                    file_items.append(
                        render_template("components/file_item.html", file=unique_filename)
                    )
            except Exception as e:
                file.seek(0)
                file.save(file_path)
                # printf"PDF text extraction error: {e}")
                file_items.append(
                    render_template("components/file_item.html", file=unique_filename)
                )
        
        elif file_extension in [".xlsx", ".xls"]:
            try:
                import openpyxl
                temp_path = os.path.join(path, f"temp_{unique_filename}")
                file.save(temp_path)
                
                # Load the workbook
                workbook = openpyxl.load_workbook(temp_path, data_only=True)
                
                # Process each sheet
                for sheet_name in workbook.sheetnames:
                    sheet = workbook[sheet_name]
                    
                    # Get all rows as list
                    rows = list(sheet.iter_rows(values_only=True))
                    
                    if not rows:
                        continue
                    
                    # Format data: each row's values on separate lines
                    formatted_text = ""
                    for row in rows:
                        # Filter out None values and convert to string
                        row_values = [str(cell) for cell in row if cell is not None]
                        if row_values:
                            formatted_text += "\n".join(row_values) + "\n\n"
                    
                    if formatted_text.strip():
                        # Save as separate text file for each sheet
                        if len(workbook.sheetnames) > 1:
                            text_filename = f"{base_filename}_{sheet_name}.txt"
                        else:
                            text_filename = f"{base_filename}.txt"
                        
                        text_path = os.path.join(path, text_filename)
                        with open(text_path, "w", encoding="utf-8") as f:
                            f.write(formatted_text)
                        
                        file_items.append(
                            render_template("components/file_item.html", file=text_filename)
                        )
                
                os.remove(temp_path)
                
            except Exception as e:
                file.seek(0)
                file.save(file_path)
                # printf"XLSX extraction error: {e}")
                file_items.append(
                    render_template("components/file_item.html", file=unique_filename)
                )
        
        else:
            file.save(file_path)
            file_items.append(
                render_template("components/file_item.html", file=unique_filename)
            )
    
    return "".join(file_items), 200  # Return all file items as HTML


@admin_bp.route("/logout")
@admin_required
def logout():
    # session.pop('user', None)
    session.clear()
    return redirect(url_for("admin.login"))


def generate_stats(chat_list):
    """Simplified and optimized stats generation."""
    if not chat_list:
        return get_empty_stats()
    
    now = datetime.utcnow()
    time_boundaries = calculate_time_boundaries(now)
    
    # Define time periods and their configurations
    periods = {
        'today': {
            'boundary': time_boundaries['today_start'],
            'format': lambda dt: dt.strftime("%H:00"),
            'labels': get_time_labels(now)['hours']
        },
        'this-week': {
            'boundary': time_boundaries['week_start'], 
            'format': lambda dt: dt.strftime("%A"),
            'labels': get_time_labels(now)['days']
        },
        'this-month': {
            'boundary': time_boundaries['month_start'],
            'format': lambda dt: dt.day,
            'labels': get_time_labels(now)['days_in_month']
        },
        'this-year': {
            'boundary': time_boundaries['year_start'],
            'format': lambda dt: dt.strftime("%b"), 
            'labels': get_time_labels(now)['months']
        },
        'all-time': {
            'boundary': None,  # No boundary for all-time
            'format': lambda dt: dt.strftime("%Y"),
            'labels': None  # Will be calculated dynamically
        }
    }
    
    # Initialize counters for all periods
    counters = {}
    for period in periods:
        counters[period] = {'total': defaultdict(int), 'admin': defaultdict(int)}
    
    # Single pass through all chats
    for chat in chat_list:
        created = chat.created_at
        is_admin_required = chat.admin_required
        
        for period_name, config in periods.items():
            # Check if chat falls within this period's boundary
            if config['boundary'] is None or created >= config['boundary']:
                label = config['format'](created)
                counters[period_name]['total'][label] += 1
                if is_admin_required:
                    counters[period_name]['admin'][label] += 1
    
    # Build final response
    result = {}
    for period_name, config in periods.items():
        labels = config['labels']
        if period_name == 'all-time':
            # For all-time, use sorted years from actual data
            labels = sorted(counters[period_name]['total'].keys())
        
        result[period_name] = {
            "labels": labels,
            "totalChats": [counters[period_name]['total'][label] for label in labels],
            "adminRequired": [counters[period_name]['admin'][label] for label in labels],
        }
    
    return result

def calculate_time_boundaries(now):
    """Pre-calculate all time boundaries."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        'today_start': today_start,
        'week_start': today_start - timedelta(days=today_start.weekday()),
        'month_start': now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        'year_start': now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    }

@lru_cache(maxsize=32)
def get_time_labels(now):
    """Get all time labels with caching."""
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    
    return {
        'hours': [f"{str(h).zfill(2)}:00" for h in range(24)],
        'days': ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        'days_in_month': list(range(1, days_in_month + 1)),
        'months': ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    }

def get_empty_stats():
    """Return empty stats structure when no chats exist."""
    now = datetime.utcnow()
    labels = get_time_labels(now)
    
    return {
        "today": {
            "labels": labels['hours'],
            "totalChats": [0] * 24,
            "adminRequired": [0] * 24,
        },
        "this-week": {
            "labels": labels['days'],
            "totalChats": [0] * 7,
            "adminRequired": [0] * 7,
        },
        "this-month": {
            "labels": labels['days_in_month'],
            "totalChats": [0] * len(labels['days_in_month']),
            "adminRequired": [0] * len(labels['days_in_month']),
        },
        "this-year": {
            "labels": labels['months'],
            "totalChats": [0] * 12,
            "adminRequired": [0] * 12,
        },
        "all-time": {
            "labels": [],
            "totalChats": [],
            "adminRequired": [],
        },
    }


def get_user(chat,user_service):
    chat.__setattr__('username',user_service.get_user_by_id(chat.user_id).name)
    return chat


@lru_cache(maxsize=256)
def get_cached_user(user_id, user_service):
    """Cache user lookups to avoid repeated database calls."""
    try:
        return user_service.get_user_by_id(user_id)
    except Exception as e:
        logger.warning(f"Failed to get user {user_id}: {e}")
        return None

def enrich_chats_with_usernames(chats, user_service):
    """Efficiently add usernames to chats using parallel processing."""
    if not chats:
        return []
    
    # Get unique user IDs to minimize database calls
    unique_user_ids = list(set(chat.user_id for chat in chats if hasattr(chat, 'user_id')))
    
    # Fetch users in parallel
    user_cache = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_user_id = {
            executor.submit(get_cached_user,
                            user_id, user_service): user_id 
            for user_id in unique_user_ids
        }
        
        for future in as_completed(future_to_user_id):
            user_id = future_to_user_id[future]
            try:
                user = future.result()
                user_cache[user_id] = user.name if user else "Unknown User"
            except Exception as e:
                logger.warning(f"Failed to fetch user {user_id}: {e}")
                user_cache[user_id] = "Unknown User"
    
    # Add usernames to chats
    for chat in chats:
        if hasattr(chat, 'user_id'):
            chat.username = user_cache.get(chat.user_id, "Unknown User")
    
    return chats


def get_dashboard_data(admin_id, chat_service, user_service, limit=50):
    """Get optimized dashboard data with 500+ limit handling."""
    # Get chats with limit+1 to detect if there are more than the limit
    chats = chat_service.get_all_chats(admin_id, limit=limit)
    
    # For stats, use higher limit with 500+ handling
    stats_limit = 501  # Get 501 to detect if there are 500+
    chats_for_stats = chat_service.get_chats_with_full_messages(admin_id, limit=stats_limit)
    
    # Handle 500+ case
    if len(chats_for_stats) == 501:
        # Truncate to 500 and note that there are more
        chats_for_stats = chats_for_stats[:500]
        # You could add a flag here if needed: has_more_than_500 = True
    
    # Generate stats from the dataset (max 500 chats)
    stats_data = generate_stats(chats_for_stats)
    
    # Enrich chats with usernames efficiently  
    enriched_chats = enrich_chats_with_usernames(chats, user_service)
    
    return enriched_chats, stats_data
@admin_bp.route("/")
@admin_bp.route("/dashboard")
@admin_required
def index():
    admin_service = AdminService(current_app.db)
    admin = admin_service.get_admin_by_id(session.get("admin_id"))
    
    if admin.onboarding:
        return redirect(url_for("admin.onboard"))
    
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    
    # Use the optimized function
    admin_id = session.get("admin_id")
    enriched_chats, stats_data = get_dashboard_data(admin_id, chat_service, user_service)
    
    return render_template(
        "admin/index.html",
        chats=enriched_chats,
        data=stats_data,
        username="Ana",
        online_users=current_app.config.get("ONLINE_USERS", 0),
    )




@admin_bp.route("/join/<room_id>")
@admin_required
def join_chat(room_id):
    chat_service = ChatService(current_app.db)
    chat = chat_service.get_chat_by_room_id(room_id)

    if not chat:
        return jsonify({"error": "Chat not found"}), 404

    # Mark admin as present in this chat
    chat_service.set_admin_present(chat.chat_id, True)

    # Notify the room that admin has joined
    current_app.socketio.emit(
        "admin_joined", {"message": "Admin has joined the chat"}, room=room_id
    )

    return render_template("chat.html", room_id=room_id, is_admin=True)


# Socket.IO events for admin




@admin_bp.route("/settings", methods=["GET"])
@admin_required
def settings():
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    # Initialize settings data based on role
    if current_admin.role == "superadmin":
        settings_data = {
            **current_app.config["SETTINGS"], **current_admin.settings}
    else:
        settings_data = current_admin.settings

    # Validate logo paths for superadmin
    if current_admin.role == "superadmin":
        settings_data["logo"]["large"] = (
            current_app.config["SETTINGS"]["logo"]["large"]
            if os.path.exists(
                os.path.join(
                    os.getcwd(
                    ), current_app.config["SETTINGS"]["logo"]["large"][1:]
                )
            )
            else ""
        )
        settings_data["logo"]["small"] = (
            current_app.config["SETTINGS"]["logo"]["small"]
            if os.path.exists(
                os.path.join(
                    os.getcwd(
                    ), current_app.config["SETTINGS"]["logo"]["small"][1:]
                )
            )
            else ""
        )

    # Sort timings by day order if they exist
    day_order = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    if settings_data.get("timings"):
        settings_data["timings"] = sorted(
            settings_data["timings"], key=lambda time: day_order[time["day"]]
        )

    # Handle Google Drive connection for all admins
    folders = []
    selected_folders = []
    if current_admin.settings.get("google_token"):
        try:
            creds = Credentials.from_authorized_user_info(
                json.loads(current_admin.settings["google_token"]), SCOPES
            )
            if creds:
                service = build("drive", "v3", credentials=creds)
                results = (
                    service.files()
                    .list(
                        q="mimeType='application/vnd.google-apps.folder'",
                        fields="files(id, name)",
                    )
                    .execute()
                )
                folders = results.get("files", [])
                selected_folders = current_admin.settings.get(
                    "selected_folders", [])
        except Exception as e:
            current_app.logger.error(
                f"Failed to load Google Drive for admin {
                    current_admin.admin_id}: {str(e)}"
            )

    if current_admin.role == 'superadmin':

        current_app.db.config.update_one({"id":"settings"},{"$set":current_app.config['SETTINGS']})

    return render_template(
        "admin/settings.html",
        settings=settings_data,
        tzs=UTCZoneManager.get_timezones(),
        folders=folders,
        selected_folders=selected_folders,
        audio_file=f"/static/sounds/message.wav"
    )


def save_settings(settings):
    session["settings"] = settings
    return True


ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "txt", "svg","mp3","mp4","wav"}


def allowed_file(filename):
    """Check if file extension is allowed."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@admin_bp.route("/update-logo/<file_name>", methods=["POST"])
@admin_required
def upload_logo(file_name):

    if "file" not in request.files:
        return "No file part", 400

    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400
    if file_name == "logo.svg":
        f_type = "large"
    elif file_name == "logo-desktop-mini.svg":
        f_type = "small"
    if file and allowed_file(file_name):
        # Prevent directory traversal attacks
        filename = secure_filename(file_name)
        file_path = os.path.join(current_app.config["LOGOS_FOLDER"], filename)
        file.save(file_path)
        current_app.config["SETTINGS"]["logo"][f_type] = os.path.join(
            "/static", "img", filename
        )
        # # # # printcurrent_app.config)
        return f"File saved at {file_path}", 200

    return "Invalid file type", 400


@admin_bp.route("/upload-sound", methods=["POST"])
@admin_required
def upload_sound():
    file_name = 'message.wav'

    if "file" not in request.files:
        return "No file part", 400

    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400
    if file and allowed_file(file_name):
        # Prevent directory traversal attacks
        filename = secure_filename(file_name)
        file_path = os.path.join(current_app.config["SOUND_FOLDER"], filename)
        file.save(file_path)
        # current_app.config["SETTINGS"]["logo"][f_type] = os.path.join(
        #     "/static", "img", filename
        # )
        # # # # printcurrent_app.config)
        # print f"File saved at {file_path}")
        return f"File saved at {file_path}", 200

    return "Invalid file type", 400



@admin_bp.route("/settings/timezone", methods=["POST"])
@admin_required
def set_timezone():
    tz = request.form.get("timezone")
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["timezone"] = tz
    else:
        current_admin.settings["timezone"] = tz
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id}, {
                "$set": {"settings.timezone": tz}}
        )
    return "", 200


@admin_bp.route("/settings/timing", methods=["POST"])
@admin_required
def add_timing():
    day = request.form.get("meetingDay")
    start_time = request.form.get("startTime")
    end_time = request.form.get("endTime")
    # timezone = request.form.get("timezone")

    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        timings = current_app.config["SETTINGS"].get("timings", [])
    else:
        timings = current_admin.settings.get("timings", [])

    # Remove existing entry for that day
    timings = [t for t in timings if t["day"] != day]

    # Add new timing entry
    timings.append({"day": day, "startTime": start_time, "endTime": end_time})

    # Sort by weekday
    day_order = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    timings.sort(key=lambda t: day_order[t["day"]])

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["timings"] = timings
        # current_app.config['SETTINGS']['timezone'] = timezone
    else:
        current_admin.settings["timings"] = timings
        # current_admin.settings['timezone'] = timezone
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id},
            {
                "$set": {
                    "settings.timings": timings,
                    # "settings.timezone": timezone
                }
            },
        )

    return "added", 200


@admin_bp.route('/settings/2fa-duration/', methods=['POST'])
@admin_required
def set_2fa_duration():

    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))
    # printcurrent_app.config['SETTINGS'])
    if current_admin.role == "superadmin":
        if not current_app.config['SETTINGS'].get('2fa', None):

            current_app.config['SETTINGS']['2fa'] = {
                "duration": None, "unit": None}
        current_app.config['SETTINGS']['2fa']['duration'] = request.form.get(
            'duration_value')
        current_app.config['SETTINGS']['2fa']['unit'] = request.form.get(
            'duration_unit')
        return "", 200
    else:
        return "", 403


@admin_bp.route('/settings/2fa/', methods=['POST'])
@admin_required
def set_2fa():
    admin_service = AdminService(current_app.db)
    admin_service.toggle_two_fa(session.get('admin_id'))
    return '', 200


@admin_bp.route("/settings/timing/<int:id>", methods=["DELETE"])
@admin_required
def delete_timing(id):
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        timings = current_app.config["SETTINGS"].get("timings", [])
    else:
        timings = current_admin.settings.get("timings", [])

    day_order = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    timings = sorted(timings, key=lambda time: day_order[time["day"]])

    if 0 <= id < len(timings):
        timings.pop(id)

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["timings"] = timings
    else:
        current_admin.settings["timings"] = timings
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id},
            {"$set": {"settings.timings": timings}},
        )

    return "delete", 200


@admin_bp.route("/settings/model/", methods=["POST"])
@admin_required
def update_model():
    model = request.form.get("model")
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["model"] = model
    else:
        current_admin.settings["model"] = model
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id}, {
                "$set": {"settings.model": model}}
        )

    current_app.bot._set_bot(model)
    return "", 200


@admin_bp.route("/settings/api/<api_type>", methods=["POST", "DELETE"])
@admin_required(roles=["superadmin"])  # Only superadmin can modify API keys
def api_key(api_type):
    if request.method == "DELETE":
        current_app.config["SETTINGS"]["apiKeys"][api_type] = ""
        return "", 200
    elif request.method == "POST":
        current_app.config["SETTINGS"]["apiKeys"][api_type] = request.form.get(
            "key")
        return "", 200
    return "", 500


@admin_bp.route("/settings/theme/<theme_type>", methods=["POST"])
@admin_required
def set_theme(theme_type):
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["theme"] = theme_type
    else:
        current_admin.settings["theme"] = theme_type
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id},
            {"$set": {"settings.theme": theme_type}},
        )
    return "", 200


@admin_bp.route("/settings/prompt", methods=["POST"])
@admin_required
def set_prompt():
    prpt = request.form.get("prompt")
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role == "superadmin":
        current_app.config["SETTINGS"]["prompt"] = prpt
    else:
        current_admin.settings["prompt"] = prpt
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id}, {
                "$set": {"settings.prompt": prpt}}
        )
    return "", 200


@admin_bp.route("/settings/subject", defaults={"subject": None}, methods=["POST"])
@admin_bp.route("/settings/subject/<string:subject>", methods=["DELETE"])
@admin_required
def subjects(subject):
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if request.method == "POST":
        subject = request.form.get("subject")
        if current_admin.role == "superadmin":
            current_app.config["SETTINGS"]["subjects"] = set(
                current_app.config["SETTINGS"].get("subjects", [])
            )
            current_app.config["SETTINGS"]["subjects"].add(subject)
        else:
            current_admin.settings["subjects"] = set(
                current_admin.settings.get("subjects", [])
            )
            current_admin.settings["subjects"].add(subject)
            admin_service.admins_collection.update_one(
                {"admin_id": current_admin.admin_id},
                {"$addToSet": {"settings.subjects": subject}},
            )
        return "", 200
    else:
        try:
            if current_admin.role == "superadmin":
                current_app.config["SETTINGS"]["subjects"].remove(subject)
            else:
                current_admin.settings["subjects"].remove(subject)
                admin_service.admins_collection.update_one(
                    {"admin_id": current_admin.admin_id},
                    {"$pull": {"settings.subjects": subject}},
                )
        except KeyError:
            pass
        return "", 200


@admin_bp.route("/settings/language", methods=["POST"])
@admin_required
def add_language():
    language = request.form.get("language")
    if not language:
        return jsonify({"error": "Language is required"}), 400

    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    try:
        if current_admin.role == "superadmin":
            # Update global settings
            languages = set(
                current_app.config["SETTINGS"].get("languages", ["English"])
            )
            languages.add(language)
            current_app.config["SETTINGS"]["languages"] = list(languages)
        else:
            # Update admin-specific settings
            languages = set(current_admin.settings.get(
                "languages", ["English"]))
            languages.add(language)
            current_admin.settings["languages"] = list(languages)

            # Update in database
            admin_service.admins_collection.update_one(
                {"admin_id": current_admin.admin_id},
                {"$addToSet": {"settings.languages": language}},
            )

        return "", 200
    except Exception as e:
        current_app.logger.error(f"Error adding language: {str(e)}")
        return jsonify({"error": "Failed to add language"}), 500


@admin_bp.route("/settings/language/<string:language>", methods=["DELETE"])
@admin_required
def remove_language(language):
    if not language:
        return jsonify({"error": "Language is required"}), 400

    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    try:
        if current_admin.role == "superadmin":
            # Update global settings
            languages = set(
                current_app.config["SETTINGS"].get("languages", ["English"])
            )
            languages.discard(language)
            current_app.config["SETTINGS"]["languages"] = list(languages)
        else:
            # Update admin-specific settings
            languages = set(current_admin.settings.get(
                "languages", ["English"]))
            languages.discard(language)
            current_admin.settings["languages"] = list(languages)

            # Update in database
            admin_service.admins_collection.update_one(
                {"admin_id": current_admin.admin_id},
                {"$pull": {"settings.languages": language}},
            )

        return "", 200
    except Exception as e:
        current_app.logger.error(f"Error removing language: {str(e)}")
        return jsonify({"error": "Failed to remove language"}), 500


def scrape_urls(urls,admin_id):
    for url in urls:
        res = scrape_web(url, rotate_user_agents=True, random_delay=True)
        if res and "text" in res:
            lines = str(res["text"])
            # # # # printlines)
            lines = re.sub(r"\s+", " ", lines).strip()
            # Create a filename from the URL
            if res["url"].endswith("/"):
                res["url"] = res["url"][:-1]
                # # # printres['url'])
            # # # printres['url'].endswith('/'))
            filename = "*".join(res["url"].split("/")[2:])
            if not filename:
                # Use domain if path is empty
                filename = urlparse(res["url"]).netloc
            filepath = f"{os.getcwd()}/user_data/{admin_id}/files/{filename}.txt"
            # printfilepath)
            with open(filepath, "w") as f:
                # # # # printf"Saving content to {f.name}")
                # if len(lines) > 500:
                # # # # printlines)
                # # # # printfilepath)
                f.write(lines)


@admin_bp.route("/scrape", methods=["POST"])
@admin_required
def scrape():
    urls = str(request.form.get("url")).rsplit()
    all_urls = []
    # Process each URL (could be a sitemap or regular page)
    for url in urls:
        # time.sleep(0.5)
        collected_urls = process_url(url)
        all_urls.extend(collected_urls)

    admin_id = session.get('admin_id')
    thread = threading.Thread(target=scrape_urls, args=(all_urls,admin_id,))
    thread.start()
    # Now scrape all the collected URLs
    # printall_urls)
    return "", 200


def process_url(url):
    """
    Process a URL which could be a sitemap or a regular page.
    Returns a list of URLs to scrape.
    """
    # First check if it's likely a sitemap based on URL pattern
    if is_likely_sitemap(url):
        return process_sitemap_url(url)
    return [url]  # Treat as regular URL if not a sitemap


def is_likely_sitemap(url):
    """
    Check if a URL is likely a sitemap without making a request.
    Returns True if URL ends with common sitemap extensions or contains 'sitemap' in path.
    """
    url_lower = url.lower()
    return (
        url_lower.endswith(".xml")
        or url_lower.endswith(".xml.gz")
        or "sitemap" in url_lower
    )


def process_sitemap_url(url):
    """
    Process a URL that's likely a sitemap.
    Returns a list of URLs found in the sitemap.
    """
    try:
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            # # # printf"Failed to fetch {url}: Status code {response.status_code}")
            return [url]  # Return original URL if we can't process it

        content_type = response.headers.get("Content-Type", "").lower()
        content = response.text

        # Check if it's actually a sitemap (even if URL suggested it might be)
        if "xml" in content_type or "<urlset" in content or "<sitemapindex" in content:
            return extract_urls_from_sitemap(content, url)

        # If URL suggested sitemap but content isn't, return original URL
        return [url]

    except Exception as e:
        # # # printf"Error processing {url}: {str(e)}")
        return [url]  # Include the original URL if processing fails


def extract_urls_from_sitemap(sitemap_content, base_url):
    """
    Extract URLs from a sitemap, handling both regular sitemaps and sitemap indexes.
    Returns a list of URLs.
    """
    urls = []
    try:
        # Parse the XML
        root = ET.fromstring(sitemap_content)
        # Handle sitemap index (collection of sitemaps)
        if root.tag.endswith("sitemapindex"):
            # This is a sitemap index, we need to process each sitemap
            for sitemap in root.findall(".//{*}sitemap"):
                loc_elem = sitemap.find(".//{*}loc")
                if loc_elem is not None and loc_elem.text:
                    # Recursively process this sitemap
                    child_sitemap_url = loc_elem.text.strip()
                    # # # printf"Found child sitemap: {child_sitemap_url}")
                    child_urls = process_sitemap_url(child_sitemap_url)
                    urls.extend(child_urls)
        # Handle regular sitemap
        elif root.tag.endswith("urlset"):
            # This is a regular sitemap with URLs
            for url_elem in root.findall(".//{*}url"):
                loc_elem = url_elem.find(".//{*}loc")
                if loc_elem is not None and loc_elem.text:
                    page_url = loc_elem.text.strip()
                    urls.append(page_url)
    except Exception as e:
        # # # printf"Error parsing sitemap from {base_url}: {str(e)}")
        # Fall back to regex-based extraction if XML parsing fails
        urls.extend(re.findall(r"<loc>(.*?)</loc>", sitemap_content))
    # # # # printf"Extracted {len(urls)} URLs from sitemap")
    return urls





@admin_bp.route('/chat-counts', methods=['GET'])
@admin_required
def get_chat_counts():
    """API endpoint to get chat counts for dynamic updating."""
    chat_service = ChatService(current_app.db)
    counts = chat_service.get_chat_counts_by_filter(session.get("admin_id"))
    return jsonify(counts)

# Also update your main chat route to include counts
@admin_bp.route("/chats/", methods=["GET"])
@admin_required
def get_all_chats():
    """Main chats page with initial data."""
    chat_service = ChatService(current_app.db)
    user_service = UserService(current_app.db)
    
    # Get initial chats
    chats = chat_service.get_chats_with_limited_messages(
        admin_id=session.get("admin_id"),
        limit=20,
        skip=0
    )
    # # printchats)   
    # Get chat counts for header

    # p# printchats)
    chat_counts = chat_service.get_chat_counts_by_filter(session.get('admin_id'))
    return render_template(
        "admin/chats.html",
        # chats=chats_data,
        chat_counts=chat_counts,
        has_more=len(chats) == 20,
        next_page=0,
        current_filter='all'
    )


@admin_bp.route("/chat/<string:room_id>/delete", methods=["POST"])
def delete_chat(room_id):
    chat_service = ChatService(current_app.db)
    # chats_all = chat_service.get_all_chats(session.get('admin_id'),limit=100)
    # chats_all.sort(key=lambda x: x.updated_at, reverse=True)
    # current_index = next((i for i, chat in enumerate(chats_all) if chat.room_id == room_id), None)
    # next_chat = chats_all[current_index + 1] if current_index is not None and current_index + 1 < len(chats_all) else None
    #
    # # # printchat_service.get_chat_by_room_id(room_id).to_dict())
    # printf"Deleted: {chat_service.delete([room_id])}")

    # if next_chat and "/admin/chats" not in request.headers.get('Hx-Current-Url'):
    #     return f"/admin/chat/{next_chat.room_id}" ,203
    return "", 200


@admin_bp.route("/chats/delete", methods=["POST"])
def delete_chats():

    data = request.get_json()
    if not data.get("chat_ids"):
        return "", 200
    chats = data["chat_ids"]
    # printchats)
    try:
        chat_service = ChatService(current_app.db)
        chats_all = chat_service.get_all_chats(session.get('admin_id'))

        chats_all.sort(key=lambda x: x.updated_at, reverse=True)
        current_index = next((i for i, chat in enumerate(chats) if chat.id == chats), None)
        next_chat = chats[current_index + 1] if current_index is not None and current_index + 1 < len(chats) else None
        # printf"next_chat: {next_chat}")
        # printrequest.__dict__)
        chat_service.delete(chats)
        return "", 200
    except Exception as e:
        return f"Error {e}",500


CREDENTIALS_FILE = "credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


@admin_bp.route("/google-login")
@admin_required
def google_connect():
    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for("admin.oauth2callback", _external=True)
    auth_url, state = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    session["google_auth_state"] = state
    return redirect(auth_url)


@admin_bp.route("/load-folders", methods=["POST"])
@admin_required
def load_folders():
    selected_folders = request.form.getlist("selected_folders")
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    # Update admin settings with selected folders
    current_admin.settings["selected_folders"] = selected_folders

    # Update in database
    admin_service.admins_collection.update_one(
        {"admin_id": current_admin.admin_id},
        {"$set": {"settings.selected_folders": selected_folders}},
    )

    return "", 200


@admin_bp.route("/google-files/")
@admin_required
def google_files():
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if not current_admin.settings.get("google_token"):
        return render_template("admin/google_files.html", files={})

    try:
        creds = Credentials.from_authorized_user_info(
            json.loads(current_admin.settings["google_token"]), SCOPES
        )
        service = build("drive", "v3", credentials=creds)

        files_by_folder = {}
        for folder_id in current_admin.settings.get("selected_folders", []):
            try:
                # Get folder name
                folder_info = (
                    service.files().get(fileId=folder_id, fields="name").execute()
                )
                folder_name = folder_info.get("name", f"Folder ({folder_id})")

                # Get files in folder
                results = (
                    service.files()
                    .list(
                        q=f"'{
                            folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'",
                        pageSize=1000,
                        fields="files(id, name, mimeType, webViewLink, thumbnailLink)",
                    )
                    .execute()
                )

                files_by_folder[folder_name] = {
                    "id": folder_id,
                    "files": results.get("files", []),
                }
            except Exception as e:
                current_app.logger.error(
                    f"Error accessing folder {
                        folder_id}: {str(e)}"
                )
                continue

        return render_template(
            "admin/google_files.html",
            files=files_by_folder,
            selected_folders=current_admin.settings.get(
                "selected_folders", []),
        )
    except Exception as e:
        current_app.logger.error(f"Failed to access Google Drive: {str(e)}")
        return render_template(
            "admin/google_files.html",
            files={},
            error=str(e),
            selected_folders=current_admin.settings.get(
                "selected_folders", []),
        )


@admin_bp.route("/google-files/view/<file_id>")
@admin_required
def view_google_file(file_id):
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))
    creds = Credentials.from_authorized_user_info(
        json.loads(current_admin.settings["google_token"]), SCOPES
    )
    service = build("drive", "v3", credentials=creds)
    file = service.files().get(fileId=file_id, fields="webViewLink").execute()
    return redirect(file.get("webViewLink", "/admin/google-files/"))


@admin_bp.route("/google-files/download", methods=["POST"])
@admin_required
def download_google_files():
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if not current_admin.settings.get("google_token"):
        return redirect("/admin/google-files/")

    file_ids = request.form.getlist("file_ids")
    if not file_ids:
        flash("No files selected for download", "warning")
        return redirect("/admin/google-files/")

    try:
        # Get the download path from config (you'll need to set this in your config)
        admin_id = session.get("admin_id")
        download_path = os.path.join(UPLOAD_FOLDER, f"{admin_id}","files")
        os.makedirs(download_path, exist_ok=True)

        creds = Credentials.from_authorized_user_info(
            json.loads(current_admin.settings["google_token"]), SCOPES
        )
        service = build("drive", "v3", credentials=creds)

        downloaded_files = []

        for file_id in file_ids:
            try:
                # Get file metadata
                file_meta = (
                    service.files()
                    .get(fileId=file_id, fields="name, mimeType")
                    .execute()
                )

                # Create safe filename
                original_name = file_meta["name"]
                safe_name = secure_filename(original_name)
                file_path = os.path.join(download_path, safe_name)

                # Handle duplicate filenames
                counter = 1
                while os.path.exists(file_path):
                    name, ext = os.path.splitext(original_name)
                    safe_name = f"{secure_filename(name)}_{counter}{ext}"
                    file_path = os.path.join(download_path, safe_name)
                    counter += 1

                # Download file content
                request_download = service.files().get_media(fileId=file_id)
                file_content = request_download.execute()

                # Save to server
                with open(file_path, "wb") as f:
                    f.write(file_content)

                downloaded_files.append(safe_name)

            except Exception as e:
                current_app.logger.error(
                    f"Error downloading file {file_id}: {str(e)}")
                continue

        if downloaded_files:
            flash(
                f"Successfully downloaded {
                    len(downloaded_files)} file(s) to server",
                "success",
            )
        else:
            flash("No files were downloaded", "warning")

        return redirect("/admin/google-files/")

    except Exception as e:
        current_app.logger.error(f"Failed to download files: {str(e)}")
        flash("Failed to download files", "error")
        return redirect("/admin/google-files/")

@admin_bp.route('/google/logout',methods=['POST'])
def google_logout():
    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES)
    
    admin_service = AdminService(current_app.db)
    admin_service.admins_collection.update_one(

        {"admin_id": session.get('admin_id')},
        {"$set": {"settings.google_token": None}},
    )
    return "",200


@admin_bp.route("/google-thumbnail/<file_id>")
def google_thumbnail(file_id):
    creds = Credentials.from_authorized_user_info(
        json.loads(current_app.config["SETTINGS"].get("google-token")), SCOPES
    )
    service = build("drive", "v3", credentials=creds)
    request = service.files().get_media(fileId=file_id)
    from googleapiclient.http import MediaIoBaseDownload
    import io

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)

    # Send image file with Flask
    from flask import send_file

    return send_file(fh, mimetype="image/jpeg")


@admin_bp.route("/oauth2callback")
@admin_required
def oauth2callback():
    state = session["google_auth_state"]
    flow = InstalledAppFlow.from_client_secrets_file(
        CREDENTIALS_FILE, scopes=SCOPES, state=state
    )
    flow.redirect_uri = url_for("admin.oauth2callback", _external=True)
    flow.fetch_token(authorization_response=request.url)

    # Store credentials in the admin's settings
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    # Update admin settings with the new token
    current_admin.settings["google_token"] = flow.credentials.to_json()
    admin_service.admins_collection.update_one(
        {"admin_id": current_admin.admin_id},
        {"$set": {"settings.google_token": flow.credentials.to_json()}},
    )

    return redirect(url_for("admin.settings"))


@admin_bp.route("/create-admin", methods=["GET", "POST"])
@admin_required(roles=["superadmin"])
def create_admin():
    # return "create admin", 200
    if request.method == "GET":
        return render_template("/admin/create-admin.html")
    elif request.method == "POST":
        try:
            form_data = request.form.to_dict()
            # # # printform_data)
            admin_service = AdminService(current_app.db)
            admin = admin_service.create_admin(
                username=form_data["username"],
                password=form_data["password"],
                email=form_data["email"],
            )

            # SEND_USER = os.environ.get('SMTP_TO')
            mail = Mail(current_app)
            status = send_email(
                form_data["email"],
                f"Go Bot account created: {admin.username}",
                f"Your account has been created.\n\nUsername:{
                    form_data['username']}\nOne Time Password:{form_data['password']}",mail
            )
            if status == "SEND":
                return "", 200
            return "Error", 500
        except Exception as e:
            # # printe)
            return f"Error: {e}", 500


@admin_bp.route("/settings/domain", methods=["POST"])
@admin_required
def add_domain():
    domain = request.form.get("domain")
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role != "superadmin":
        current_admin.settings["domains"] = set(
            current_admin.settings.get("domains", [])
        )
        current_admin.settings["domains"].add(domain)
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id},
            {"$addToSet": {"settings.domains": domain}},
        )
    return "", 200


@admin_bp.route("/settings/domain/<domain>", methods=["DELETE"])
@admin_required
def remove_domain(domain):
    admin_service = AdminService(current_app.db)
    current_admin = admin_service.get_admin_by_id(session.get("admin_id"))

    if current_admin.role != "superadmin":
        current_admin.settings["domains"] = set(
            current_admin.settings.get("domains", [])
        )
        current_admin.settings["domains"].discard(domain)
        admin_service.admins_collection.update_one(
            {"admin_id": current_admin.admin_id},
            {"$pull": {"settings.domains": domain}},
        )
    return "", 200


@admin_bp.route("/notifications/")
@admin_required
def get_notifications():
    noti_service = NotificationService(current_app.db)
    notis = noti_service.get_notifications(
        session.get("admin_id"), unread_only=True
    )
    chat_service = ChatService(current_app.db)
    notificaitons = []

    for noti in notis:
        chat = chat_service.get_chat_by_room_id(noti.get('room_id'))
        if chat:
            notificaitons.append({**noti, **chat.to_dict()})

    return render_template(
        "components/notification-list.html", notifications=notificaitons
    )


@admin_bp.route("/notification/<notification_id>/", methods=['POST'])
@admin_required
def viewed_notifications(notification_id):
    noti_service = NotificationService(current_app.db)

    if noti_service.mark_notification_read(notification_id, session.get('admin_id')):

        return "", 200
    else:
        return "Notification not updated", 500


@admin_bp.route('/contact/',methods=['GET','POST'])
@admin_required
def contact():
    admin_service = AdminService(current_app.db)
    admin = admin_service.get_admin_by_id(session.get('admin_id'))
    if request.method == 'GET':
        return render_template('/admin/contact.html', admin=admin)
    else:
        SMTP_USER = os.environ.get('SMTP_TO')
        form_data = request.json
        mail = Mail(current_app)
        # printdict(form_data.items()))
        send_email(SMTP_USER, f"Go Bot Contact query from: {form_data['name']}", message="New contact", mail=mail,html_message=render_template('email/contact.html',name=form_data['name'],email=form_data['email'],phone=form_data['phone'],subject=form_data['subject'],message=form_data['message'],admin_id=session.get('admin_id'),time=datetime.now()))
        return jsonify({
                    'success': True,
                    'message': 'Your message has been sent successfully!'
                }), 200


import pickle 
from services.database_service import DatabaseCrawler
import os


def get_user_crawler(admin_id: str) -> DatabaseCrawler:
    """Get or create user's database crawler"""
    user_dir = os.path.join('user_data', admin_id)
    os.makedirs(user_dir, exist_ok=True)
    
    db_path = os.path.join(user_dir, 'db_connection.pkl')
    
    if os.path.exists(db_path):
        with open(db_path, 'rb') as f:
            return pickle.load(f)
    else:
        return DatabaseCrawler()

import dill

def save_user_crawler(admin_id: str, crawler: DatabaseCrawler):
    """Save user's database crawler"""
    user_dir = os.path.join('user_data', admin_id)
    os.makedirs(user_dir, exist_ok=True)
    
    db_path = os.path.join(user_dir, 'db_connection.pkl')
    # printcrawler)
    # printdb_path)

    # printf"crawler: {crawler}")
    # printf"crawler.connectors: {crawler.connectors}")

    with open(db_path, 'wb') as f:
        pickle.dump(crawler, f)

@admin_bp.route('/database/')
@admin_required
def database_homepage():
    admin_id = session.get('admin_id')
    crawler =get_user_crawler(admin_id) 
    # printf"{crawler}")
    # path = os.path.join('user_data',admin_id,"db_connection.pkl") 
    # if os.path.exists(path):
    #     with open(path, 'rb') as file:
    #         connection = pickle.load(file)
    # else:
    #     crawler = DatabaseCrawler()
    return render_template('admin/database.html',crawler=crawler)

@admin_bp.route('/test_database_connection', methods=['POST'])
@admin_required
def test_database_connection():
    """Test database connection"""
    data = request.form
    
    try:
        connection_type = data['type']
        temp_crawler = DatabaseCrawler()
        
        if connection_type == 'mysql':
            # MySQL connection test
            temp_crawler.add_mysql_connection(
                name='temp_test',
                host=data['host'],
                port=int(data['port']),
                username=data.get('username'),
                password=data.get('password'),
                database=data.get('database')
            )
        elif connection_type == 'mongodb':
            # Check if we're using URI or standard connection
            if 'connection_uri' in data:
                # MongoDB URI connection test
                temp_crawler.add_mongodb_connection(
                    name='temp_test',
                    connection_uri=data['connection_uri'],
                    database=data.get('mongodb_database')
                )
            else:
                # Standard MongoDB connection test
                temp_crawler.add_mongodb_connection(
                    name='temp_test',
                    host=data['host'],
                    port=int(data['port']),
                    username=data.get('username'),
                    password=data.get('password'),
                    database=data.get('database')
                )
        else:
            return jsonify({
                'status': 'failed',
                'database_type': connection_type,
                'message': 'Invalid database type',
                'timestamp': datetime.now().isoformat()
            }), 400
        
        # Test the connection
        result = temp_crawler.test_connection('temp_test')
        temp_crawler.close_all()
        
        return jsonify(result)
    except Exception as e:
        # printf"Error testing connection: {str(e)}")
        return jsonify({
            'status': 'failed',
            'database_type': data.get('type', 'unknown'),
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }), 400

@admin_bp.route('/add_database_connection', methods=['POST'])
@admin_required
def add_database_connection():
    """Add new database connection"""
    admin_id = session.get('admin_id')
    data = request.form

    # Validate required fields
    if not all(key in data for key in ['name', 'type']):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        crawler = get_user_crawler(admin_id)

        # Check if connection name already exists
        if data['name'] in crawler.connectors:
            return jsonify({'error': 'Connection name already exists'}), 400

        connection_type = data['type']
        name = data['name']

        if connection_type == 'mysql':
            # Validate required MySQL fields
            if not all(key in data for key in ['host', 'port']):
                return jsonify({'error': 'Missing MySQL connection parameters'}), 400

            crawler.add_mysql_connection(
                name=name,
                host=data['host'],
                port=int(data['port']),
                username=data.get('username'),
                password=data.get('password'),
                database=data.get('database')
            )

        elif connection_type == 'mongodb':
            if 'connection_uri' in data:
                crawler.add_mongodb_connection(
                    name=name,
                    connection_uri=data['connection_uri'],
                    database=data.get('mongodb_database')
                )
            else:
                if not all(key in data for key in ['host', 'port']):
                    return jsonify({'error': 'Missing MongoDB connection parameters'}), 400

                crawler.add_mongodb_connection(
                    name=name,
                    host=data['host'],
                    port=int(data['port']),
                    username=data.get('username'),
                    password=data.get('password'),
                    database=data.get('database')
                )
        else:
            return jsonify({'error': 'Invalid database type'}), 400

        # Save the updated crawler
        save_user_crawler(admin_id, crawler)

        return jsonify({'success': True, 'message': 'Connection added successfully'})

    except ValueError as e:
        return jsonify({'error': f'Invalid port number: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to add connection: {str(e)}'}), 500



@admin_bp.route('/test_db/<string:connection_name>',methods=['POST'])
@admin_required
def test_connection(connection_name):

    admin_id = session.get('admin_id')
    # connection_name = request.args.get('connection')
    
    if not connection_name:
        return jsonify({'error': 'Connection name required'}), 400
    
    try:
        crawler = get_user_crawler(admin_id)

        if connection_name not in crawler.connectors:
            return jsonify({'error': 'Connection not found'}), 404

        # connection = crawler.connectors[connection_name]
        # data = connection.test_connection()
        data = crawler.test_connection(connection_name)
        # crawler.connectors[connection_name] = connection
        # # printf"{connection}")
        # # printf"{crawler}")
        save_user_crawler(admin_id,crawler)
        return data, 200 if data['status'] == 'success' else 500
    
    except Exception as e:
        return jsonify({'error': f'Failed to get tables: {str(e)}'}), 500

@admin_bp.route('/get_database_tables')
@admin_required
def get_database_tables():
    """Get tables for a specific connection"""
    admin_id = session.get('admin_id')
    connection_name = request.args.get('connection')
    
    if not connection_name:
        return jsonify({'error': 'Connection name required'}), 400
    
    try:
        crawler = get_user_crawler(admin_id)
    
        
        if connection_name not in crawler.connectors:
            return jsonify({'error': 'Connection not found'}), 404
        
        tables = crawler.get_tables(connection_name)
        
        return jsonify({
            'success': True,
            'tables': tables,
            'connection': connection_name
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to get tables: {str(e)}'}), 500


@admin_bp.route('/get_table_data', methods=['POST'])
@admin_required
def get_table_data():
    """Get data from a specific table with optional query"""
    admin_id = session.get('admin_id')
    data = request.json
    
    if not all(key in data for key in ['connection', 'table']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        crawler = get_user_crawler(admin_id)
        
        if data['connection'] not in crawler.connectors:
            return jsonify({'error': 'Connection not found'}), 404
        
        # Get the query (if provided)
        query = data.get('query', '')
        limit = data.get('limit', 3)
        
        # For MySQL, add LIMIT if not already in query
        if crawler.connectors[data['connection']].type == 'mysql':
            if query and 'limit' not in query.lower():
                if 'where' in query.lower():
                    query += f" LIMIT {limit}"
                else:
                    query = f"SELECT * FROM {data['table']} LIMIT {limit}"
            elif not query:
                query = f"SELECT * FROM {data['table']} LIMIT {limit}"
        
        # Execute the query
        # printdata['connection'])
        result = crawler.execute_query(data['connection'], query, data['table'])
        # printresult)
        
        # Apply limit if not already applied in query (for MongoDB)
        if 'limit' not in query.lower() and len(result['data']) > limit:
            result['data'] = result['data'][:limit]
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': f'Failed to get table data: {str(e)}'}), 500
import json

def save_db_data(result, connection_name, admin_id, query=None):
    # Create directory if it doesn't exist
    db_dir = os.path.join('user_data', admin_id, 'db')
    os.makedirs(db_dir, exist_ok=True)
    
    # Prepare data to save in the new format
    data_to_save = {
        'query': query or '',
        'data': result['data']
    }
    
    with open(os.path.join(db_dir, f"{connection_name}-{result['table_names'][0]}.json"), "w") as file:
        json.dump(data_to_save, file, indent=4, default=str)

@admin_bp.route('/save_data', methods=['POST'])
@admin_required
def save_data():
    """Save selected data to backend"""
    admin_id = session.get('admin_id')
    data = request.json
    # printdata)
    
    if not all(key in data for key in ['connection', 'table']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        crawler = get_user_crawler(admin_id)
        
        if data['connection'] not in crawler.connectors:
            return jsonify({'error': 'Connection not found'}), 404
        
        # Get the query (if provided)
        query = data.get('query')
        
        # Execute the query to get all data (not just preview)
        if not query:
            query =f'SELECT * from {data['table']}' 

        result = crawler.execute_query(data['connection'], query, data['table'])
        
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']})
        
        # Save the data
        save_db_data(result, data['connection'], admin_id, query)
        
        return jsonify({
            'success': True,
            'message': f"Saved {len(result['data'])} rows from {data['table']}",
            'row_count': len(result['data'])
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to save data: {str(e)}'})

from glob import glob

@admin_bp.route('/get_saved_data')
@admin_required
def get_saved_data():
    """Get all saved data collections"""
    admin_id = session.get('admin_id')
    db_dir = os.path.join('user_data', admin_id, 'db')
    
    if not os.path.exists(db_dir):
        return jsonify({'collections': []})
    
    # Group files by connection name
    collections = {}
    for file_path in glob(os.path.join(db_dir, '*.json')):
        filename = os.path.basename(file_path)
        try:
            # Extract connection and table name from filename
            parts = filename.split('-', 1)
            if len(parts) != 2:
                continue
                
            connection_name = parts[0]
            table_name = parts[1].replace('.json', '')
            
            # Get file stats for last modified time
            stat = os.stat(file_path)
            saved_at = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            
            # Get row count
            with open(file_path, 'r') as f:
                data = json.load(f)
                row_count = len(data)
            
            # Add to collections
            if connection_name not in collections:
                collections[connection_name] = {
                    'connection_name': connection_name,
                    'tables': []
                }
            
            collections[connection_name]['tables'].append({
                'name': table_name,
                'row_count': row_count,
                'saved_at': saved_at,
                # Try to get query from metadata if available
                'query': data[0].get('_query') if data and isinstance(data, list) and len(data) > 0 else None
            })
        except Exception as e:
            # printf"Error processing {filename}: {str(e)}")
            continue
    
    return jsonify({
        'collections': list(collections.values())
    })

@admin_bp.route('/get_saved_tables')
@admin_required
def get_saved_tables():
    """Get tables for a specific saved collection"""
    admin_id = session.get('admin_id')
    connection_name = request.args.get('connection')
    
    if not connection_name:
        return jsonify({'error': 'Connection name required'}), 400
    
    try:
        db_dir = os.path.join('user_data', admin_id, 'db')
        if not os.path.exists(db_dir):
            return jsonify({'tables': []})
            
        tables = []
        for file_path in glob(os.path.join(db_dir, f'{connection_name}-*.json')):
            try:
                filename = os.path.basename(file_path)
                table_name = filename[len(connection_name)+1:-5]  # Remove connection- and .json
                
                # Get file stats
                stat = os.stat(file_path)
                saved_at = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                
                # Get row count and query
                with open(file_path, 'r') as f:
                    saved_data = json.load(f)
                    if isinstance(saved_data, dict) and 'data' in saved_data:
                        row_count = len(saved_data['data'])
                        query = saved_data.get('query', '')
                    else:
                        row_count = len(saved_data)
                        query = ''
                
                tables.append({
                    'name': table_name,
                    'row_count': row_count,
                    'saved_at': saved_at,
                    'query': query,'data':saved_data['data']
                })
            except Exception as e:
                # printf"Error processing {filename}: {str(e)}")
                continue
        # printtables)
        
        return jsonify({'tables': tables})
    
    except Exception as e:
        # printf"Error in get_saved_tables: {str(e)}")
        return jsonify({'error': str(e)}), 500
@admin_bp.route('/delete_database_connection/<connection_name>',methods=['DELETE'])
@admin_required
def delete_connection(connection_name):

    admin_id = session.get('admin_id')

    if not connection_name:
        return jsonify({'error': 'Connection and table name required'}), 400
    try:

        crawler = get_user_crawler(admin_id)
        del crawler.connectors[connection_name]

        save_user_crawler(admin_id,crawler)
        return "success",200
    except Exception as e:
        return jsonify({'error':e}),400

@admin_bp.route('/delete_saved_table/<connection_name>/<table_name>',methods=['DELETE'])
@admin_required
def delete_table(connection_name,table_name):
    admin_id = session.get('admin_id')

    if not connection_name or not table_name:
        return jsonify({'error': 'Connection and table name required'}), 400

    file_path = os.path.join('user_data', admin_id, 'db', f'{connection_name}-{table_name}.json')
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Table data not found'}), 404
    os.remove(file_path)
    return "deleted",200

@admin_bp.route('/get_saved_table_data')
@admin_required
def get_saved_table_data():
    """Get data for a specific saved table"""
    admin_id = session.get('admin_id')
    connection_name = request.args.get('connection')
    table_name = request.args.get('table')
    
    if not connection_name or not table_name:
        return jsonify({'error': 'Connection and table name required'}), 400
    
    file_path = os.path.join('user_data', admin_id, 'db', f'{connection_name}-{table_name}.json')
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Table data not found'}), 404
    
    try:
        with open(file_path, 'r') as f:
            saved_data = json.load(f)
            
            # Handle both old and new formats
            if isinstance(saved_data, dict) and 'data' in saved_data:
                # New format
                return jsonify({
                    'data': saved_data['data'],
                    'query': saved_data.get('query', '')
                })
            else:
                # Old format (array)
                return jsonify({
                    'data': saved_data,
                    'query': ''
                })
    except Exception as e:
        return jsonify({'error': f'Failed to load table data: {str(e)}'}), 500


from  pprint import pprint



####################################### CALL #############################################

@admin_bp.route("/calls/", methods=["GET"])
@admin_required
def get_all_calls():
    """Main calls page with initial data."""
    call_service = CallService(current_app.db)
    
    # Get initial calls with limited data
    calls = call_service.get_calls_with_limited_data(
        admin_id=session.get("admin_id"),
        limit=20,
        skip=0
    )
    # p# printcalls)
    
    # Get call counts for dropdown
    call_counts = call_service.get_call_counts_by_filter(session.get('admin_id'))
    
    return render_template(
        "admin/calls.html",
        calls=calls,
        call_counts=call_counts,
        has_more=len(calls) == 20,
        next_page=1,
        current_filter='all'
    )

@admin_bp.route("/call/<call_id>")
@admin_required
def get_call(call_id):
    call_service = CallService(current_app.db)
    call = call_service.get_full_call(call_id)

    if request.headers.get("HX-Request"):
        return render_template(
            "components/call.html",
            call=call,
        )

    calls = call_service.get_calls_with_limited_data(
        admin_id=session.get("admin_id"),
        limit=20,
        skip=0
    )
    
    # Get call counts for dropdown
    call_counts = call_service.get_call_counts_by_filter(session.get('admin_id'))
    
    return render_template(
        "admin/calls.html",
        calls=calls,
        call=call,
        call_counts=call_counts,
        has_more=len(calls) == 20,
        next_page=1,
        current_filter='all'
    )


@admin_bp.route("/call/<call_id>/delete",methods=["POST"])
@admin_required
def delete_call(call_id):
    print("delete call")
    call_service = CallService(current_app.db)
    if call_service.delete_call(call_id):
        return "",200
    return "",500
    


@admin_bp.route("/call/<call_id>/audio")
@admin_required
def send_audio_file(call_id):
    return send_file(f"recordings/call_{call_id}.wav", mimetype="audio/wav")


@admin_bp.route("/calls/<filter>", methods=["GET"])
@admin_required
def filter_calls(filter):
    """Filter calls by status with pagination."""
    call_service = CallService(current_app.db)
    
    page = int(request.args.get('page', 0))
    limit = 20
    skip = page * limit
    is_pagination = request.args.get('pagination', 'false') == 'true'
    
    # Map filter to status
    filter_map = {
        'all': 'all',
        'ongoing': 'ongoing',
        'ended': 'ended',
        'in_progress': 'in_progress'
    }
    
    filter_type = filter_map.get(filter, 'all')
    
    # Get filtered calls
    calls = call_service.get_calls_with_limited_data(
        admin_id=session.get("admin_id"),
        limit=limit,
        skip=skip,
        filter_type=filter_type
    )
    
    # Check if there are more calls
    has_more = len(calls) == limit
    
    if is_pagination:
        # Return only the call items for infinite scroll
        return render_template(
            "components/call-list-items.html",
            calls=calls,
            has_more=has_more,
            next_page=page + 1,
            current_filter=filter
        )
    else:
        # Return the full call list container
        return render_template(
            "components/call-list.html",
            calls=calls,
            has_more=has_more,
            next_page=page + 1,
            current_filter=filter
        )


@admin_bp.route("/calls_list/", methods=["GET"])
@admin_required
def get_calls_list():
    """Get calls list (used for real-time updates via Socket.IO)."""
    call_service = CallService(current_app.db)
    
    calls = call_service.get_calls_with_limited_data(
        admin_id=session.get("admin_id"),
        limit=20,
        skip=0
    )
    
    return render_template(
        "components/call-list.html",
        calls=calls,
        has_more=len(calls) == 20,
        next_page=1,
        current_filter='all'
    )


@admin_bp.route("/call-counts", methods=["GET"])
@admin_required
def get_call_counts():
    """API endpoint to get call counts for all filters."""
    call_service = CallService(current_app.db)
    counts = call_service.get_call_counts_by_filter(session.get('admin_id'))
    return jsonify(counts)



WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = "v24.0"

print(WHATSAPP_TOKEN)


@admin_bp.route("/whatsapp/")
@admin_required
def dashboard():
     
    wa_service = WhatsappService(current_app.db)
    chats = wa_service.get_all_chats()
    # print(chats)
    return render_template("admin/whatsapp.html",chats=chats)

@admin_bp.route("/whatsapp/<phone_no>")
@admin_required
def get_wa_chat(phone_no):
     
    wa_service = WhatsappService(current_app.db)
    chat = wa_service.get_by_phone_no(phone_no)
    if request.headers.get("HX-Request"):
        return render_template("components/whatsapp-chat-area.html",chat=chat)

    chats = wa_service.get_all_chats()
    return render_template("admin/whatsapp.html",chat=chat,chats=chats)


@admin_bp.route("/whatsapp/get-all-chats")
def whatsapp_chats():
    wa_service = WhatsappService(current_app.db)
    chats = wa_service.get_all_chats()
    pass 

@admin_bp.route("/whatsapp/<phone_no>/toggle_admin_enable")
@admin_required
def toggle_admin(phone_no):
    wa_service = WhatsappService(current_app.db)
    if wa_service.toggle_enabled_admin(phone_no):
        return "",200
    return "",500


@admin_bp.route("/whatsapp/<phone_no>/audio_file/<message_id>/")
@admin_required
def wa_audio_file(phone_no, message_id):
    base_dir = os.path.join('files', phone_no) 
    file_path = os.path.join(base_dir, f"{message_id}.ogg")
    print(file_path)
    if not os.path.exists(file_path):
        abort(404, description="Audio file not found")
    return send_from_directory(base_dir, f"{message_id}.ogg", mimetype="audio/ogg")

@admin_bp.route("/whatsapp/<phone_no>/intervene",methods=["POST"])
def wa_intervene(phone_no):
    whatsapp_service = WhatsappService(current_app.db)
    print("INTERVENE")
    if whatsapp_service.toggle_enabled_admin(phone_no):
        return "",200
    return "",500



@admin_bp.route("/whatsapp/<phone_no>/send_message", methods=["POST"])
@admin_required
def wa_send_message(phone_no):
    """
    Send a WhatsApp text message manually from the admin dashboard.
    """
    try:
        # Get message text
        message = request.form.get("message")
        if not message:
            if request.headers.get("HX-Request"):
                return "Message cannot be empty", 400
            return jsonify({"error": "Message cannot be empty"}), 400

        # WhatsApp Graph API endpoint
        url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": f"+{phone_no}",
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message
            }
        }
        print(payload)
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()
        print(data)
        print(response)
        # Optionally save to your DB
        if hasattr(current_app, "db"):
            try:
                from services.whatsapp_service import WhatsappService
                wa_service = WhatsappService(current_app.db)
                wa_service.add_message(message, phone_no, "admin", type="text")
            except Exception as e:
                print(f"[WARN] Could not log message to DB: {e}")

        # Handle HTMX vs JSON
        # if request.headers.get("HX-Request"):
        #     return f"<p class='text-green-600'>Message sent to {phone_no}</p>", 200

        return jsonify({
            "status": "success",
            "to": phone_no,
            "message": message,
            "whatsapp_response": data
        }), 200

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] WhatsApp API failed: {e}")
        if request.headers.get("HX-Request"):
            return f"<p class='text-red-600'>Failed to send message: {str(e)}</p>", 500
        return jsonify({"error": str(e)}), 500


@admin_bp.route("/whatsapp/<phone_no>/send_audio", methods=["POST"])
@admin_required
def wa_send_audio(phone_no):
    """
    Send an audio file via WhatsApp from admin dashboard.
    """
    if 'audio' not in request.files:
        if request.headers.get('HX-Request'):
            return "No audio file provided", 400
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    audio_bytes = audio_file.read()

    try:
        # Upload to WhatsApp
        upload_url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        files = {'file': ('audio.ogg', audio_bytes, 'audio/ogg; codecs=opus')}
        data = {'messaging_product': 'whatsapp'}

        upload_response = requests.post(upload_url, headers=headers, files=files, data=data)
        upload_response.raise_for_status()
        media_id = upload_response.json().get("id")

        if not media_id:
            return jsonify({"error": "Upload failed - no media ID"}), 400

        # Send the uploaded audio
        send_url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone_no,
            "type": "audio",
            "audio": {"id": media_id}
        }

        send_response = requests.post(send_url, headers={**headers, "Content-Type": "application/json"}, json=payload)
        send_response.raise_for_status()

        return jsonify({"status": "success", "to": phone_no}), 200

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to send audio: {e}")
        return jsonify({"error": str(e)}), 500



def register_admin_socketio_events(socketio):
    @socketio.on("admin_join")
    def on_admin_join(data):
        if session.get("role") != "admin":
            return

        chat_service = ChatService(current_app.db)
        chats = chat_service.get_all_chats(session.get('admin_id'))

        room = data.get("room")
        if not room:
            return
        join_room(room)
        join_room("admin")  # Join the admin room for broadcasts
        emit("status", {"msg": "Admin has joined the room."}, room=room)

    @socketio.on("admin_required")
    def on_admin_required(data):
        print(f"ADMIN REQUIRED: {data}")

    @socketio.on("new_message")
    def on_new_message(data):
        print(dict(session))
