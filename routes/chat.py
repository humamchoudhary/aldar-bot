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

@chat_bp.before_request
def redirect_admin():
    return redirect(url_for("admin.index"))
