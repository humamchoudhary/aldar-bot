from flask import (
    render_template,
    session,
    request,
    jsonify,
    redirect,
    url_for,
    current_app,
)
from flask_socketio import join_room, leave_room, emit
from . import chat_bp
from services.tempuser_service import TempUserService
from services.usage_service import UsageService
from services.tempchat_service import TempChatService
from functools import wraps
import os
from services.email_service import send_email


# @chat_bp.before_requrest
# def remove_chats():
#     pass


def user_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.create_anonymous_user"))
        return f(*args, **kwargs)

    return decorated_function


@chat_bp.route("/")
@user_required
def index():
    temp_user_service = TempUserService()
    temp_chat_service = TempChatService()

    user = temp_user_service.get_user_by_id(session["user_id"])
    if not user:
        return redirect(url_for("auth.create_anonymous_user"))

    # Get user's chats
    chats = temp_chat_service.get_user_chats(user.user_id)

    if request.headers.get("HX_Request"):
        return render_template(
            "user/fragments/chat_page.html", chats=chats, username=user.name
        )
    return render_template("user/index.html", chats=chats, username=user.name)


@chat_bp.route("/chat/<chat_id>", methods=["GET"])
@user_required
def chat(chat_id):
    temp_user_service = TempUserService()
    temp_chat_service = TempChatService()

    user = temp_user_service.get_user_by_id(session["user_id"])
    if not user:
        return redirect(url_for("auth.create_anonymous_user"))

    chat = temp_chat_service.get_chat_by_id(chat_id)
    if not chat or chat.user_id != user.user_id:
        return redirect(url_for("chat.index"))

    chats = temp_chat_service.get_user_chats(user.user_id)

    if request.headers.get("HX-Request"):
        return render_template(
            "user/fragments/chat_page.html", chat=chat, chats=chats, username=user.name
        )

    return render_template(
        "user/index.html", chat=chat, chats=chats, username=user.name
    )


@chat_bp.route("/chat/<chat_id>/ping_admin", methods=["POST", "GET"])
@user_required
def ping_admin(chat_id):
    from datetime import datetime

    if request.method == "GET":
        return redirect(f"/chat/{chat_id}")

    # Step 1: Check if current time falls within allowed timings
    now = datetime.now()
    current_day = now.strftime("%A").lower()
    current_time = now.strftime("%H:%M")

    timings = current_app.config["SETTINGS"].get("timings", [])
    timezone = current_app.config["SETTINGS"].get("timezone", "UTC")

    available = any(
        t["day"].lower() == current_day
        and t["startTime"] <= current_time <= t["endTime"]
        for t in timings
    )

    temp_chat_service = TempChatService()
    temp_user_service = TempUserService()

    user = temp_user_service.get_user_by_id(session["user_id"])
    chat = temp_chat_service.get_chat_by_id(chat_id)

    if not chat or chat.user_id != user.user_id:
        if request.headers.get("HX-Request"):
            return "Chat not found", 404
        return jsonify({"error": "Chat not found"}), 404

    if chat.admin_required:
        return "", 304

    temp_chat_service.set_admin_required(chat.chat_id, True)

    current_app.socketio.emit(
        "admin_required",
        {"room_id": chat.room_id, "chat_id": chat.chat_id, "subject": chat.subject},
        room="admin",
    )

    if not available:
        formatted_timings = "\n".join(
            f"• {t['day'].capitalize()}: {t['startTime']} - {t['endTime']} {timezone}\n"
            for t in timings
        )

        message_content = (
            "Ana has been notified, but she is currently unavailable.\n\n"
            "You can reach her during the following times:\n\n"
            f"{formatted_timings}"
        )

        new_message = temp_chat_service.add_message(
            chat.chat_id, "SYSTEM", message_content
        )

        current_app.socketio.emit(
            "new_message",
            {
                "sender": "SYSTEM",
                "content": new_message.content,
                "timestamp": new_message.timestamp.isoformat(),
            },
            room=chat.room_id,
        )
    else:
        new_message = temp_chat_service.add_message(
            chat.chat_id, "SYSTEM", "Ana has been notified! She will join soon"
        )
        current_app.socketio.emit(
            "new_message",
            {
                "sender": "SYSTEM",
                "content": new_message.content,
                "timestamp": new_message.timestamp.isoformat(),
            },
            room=chat.room_id,
        )

    # print("ANNA PINGED")
    msg = f"""Hi Ana,

{user.name} has just requested to have a live chat. If you'd like to start the conversation, simply click the link below:

{current_app.config['SETTINGS']['backend_url']}/admin/chat/{chat.room_id}

Auto Generated Message"""

    SEND_USER = os.environ.get("SMTP_TO")
    # print(SEND_USER)
    send_email(SEND_USER, f"Assistance Required: {chat.subject}", msg)

    if request.headers.get("HX-Request"):
        return "", 204

    return jsonify({"status": "Ana has been notified"}), 200


@chat_bp.route("/chat/<chat_id>/send_message", methods=["POST"])
@user_required
def send_message(chat_id):
    message = request.form.get("message")
    if not message:
        return "", 302

    temp_user_service = TempUserService()
    temp_chat_service = TempChatService()

    user = temp_user_service.get_user_by_id(session["user_id"])
    if not user:
        if request.headers.get("HX-Request"):
            return "User not found", 404
        return jsonify({"error": "User not found"}), 401

    chat = temp_chat_service.get_chat_by_id(chat_id)
    if not chat or chat.user_id != user.user_id:
        if request.headers.get("HX-Request"):
            return "Chat not found", 404
        return jsonify({"error": "Chat not found"}), 404

    new_message = temp_chat_service.add_message(chat.chat_id, user.name, message)

    current_app.socketio.emit(
        "new_message",
        {
            "sender": user.name,
            "content": message,
            "timestamp": new_message.timestamp.isoformat(),
        },
        room=chat.room_id,
    )

    if not chat.admin_required:
        msg, usage = current_app.bot.responed(message, chat.room_id)
        # print(msg)
        # print(usage)

        usage_service = UsageService(current_app.db)
        usage_service.add_cost(usage["input"], usage["output"], usage["cost"])

        bot_message = temp_chat_service.add_message(chat.chat_id, chat.bot_name, msg)

        current_app.socketio.emit(
            "new_message",
            {
                "sender": chat.bot_name,
                "content": msg,
                "timestamp": bot_message.timestamp.isoformat(),
            },
            room=chat.room_id,
        )

    return render_template(
        "user/fragments/chat_message.html", message=new_message, username=user.name
    )


@chat_bp.route("/newchat/<string:subject>", methods=["GET"])
@user_required
def new_chat(subject):
    temp_user_service = TempUserService()
    temp_chat_service = TempChatService()

    user = temp_user_service.get_user_by_id(session["user_id"])
    if not user:
        return redirect(url_for("auth.create_anonymous_user"))

    # Create a new chat
    chat = temp_chat_service.create_chat(user.user_id, subject=subject)
    current_app.bot.create_chat(chat.room_id)

    chats = temp_chat_service.get_user_chats(user.user_id)

    if request.headers.get("HX-Request"):  # HTMX request
        return render_template(
            "user/fragments/chat_page.html", chat=chat, chats=chats, username=user.name
        )

    return redirect(url_for("chat.chat", chat_id=chat.chat_id))


@chat_bp.route("/pricing")
def pricing_page():
    return render_template("user/pricing.html")


@chat_bp.route("/change-logs")
def changelogs_page():
    return render_template("user/change-logs.html")


@chat_bp.route("/faq")
def faq_page():
    return render_template("user/faq.html")


def register_socketio_events(socketio):
    @socketio.on("join")
    def on_join(data):
        room = data.get("room")
        temp_user_id = session.get("user_id")

        if not room or not temp_user_id:
            return

        temp_user_service = TempUserService()
        user = temp_user_service.get_user_by_id(temp_user_id)
        if not user:
            return

        join_room(room)
        temp_user_service.update_last_active(temp_user_id)
        # print(f'{user.name} has joined the room.')
        emit("status", {"msg": f"{user.name} has joined the room."}, room=room)

    @socketio.on("leave")
    def on_leave(data):
        room = data.get("room")
        temp_user_id = session.get("user_id")

        if not room or not temp_user_id:
            return

        temp_user_service = TempUserService()
        user = temp_user_service.get_user_by_id(temp_user_id)
        if not user:
            return

        leave_room(room)
        emit("status", {"msg": f"{user.name} has left the room."}, room=room)
