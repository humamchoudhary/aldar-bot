import random
from flask import url_for, redirect, session, request, jsonify, render_template, current_app
from . import auth_bp
from services.tempuser_service import TempUserService


def generate_random_username():
    return f"user_{random.randint(1000, 9999)}"


@auth_bp.route('/set-username', methods=['POST'])
def set_username():
    data = request.json
    name = data.get('name')

    if not name:
        return jsonify({"error": "Name is required"}), 400

    temp_user_service = TempUserService()

    # If user already has a session, update their name
    if 'temp_user_id' in session:
        user = temp_user_service.get_user_by_id(session['temp_user_id'])
        if user:
            user.name = name
            temp_user_service.update_user(user)
            return jsonify({"user_id": user.user_id, "name": name}), 200

    # Create a new anonymous user
    user = temp_user_service.create_user(name)
    session['user_id'] = user.user_id
    session['role'] = 'user'
    session.permanent = True

    return jsonify({"user_id": user.user_id, "name": name}), 201


@auth_bp.route('/login', methods=['GET'])
def login():
    # Skip login page, directly create anonymous user and redirect
    return redirect(url_for('auth.create_anonymous_user'))


@auth_bp.route('/create_anonymous_user', methods=['GET'])
def create_anonymous_user():
    # Always create anonymous user
    temp_user_service = TempUserService()

    # Generate random username
    name = generate_random_username()
    user_ip = request.headers.get(
        "X_Real-IP", request.remote_addr).split(",")[0]

    user = temp_user_service.create_user(name, ip=user_ip)

    # Store user details in session
    session['user_id'] = user.user_id
    session['role'] = "user"
    session.permanent = True

    if request.args.get('redir'):
        return redirect(url_for(request.args.get('redir')))
    else:
        return redirect(url_for('chat.index'))


@auth_bp.route('/auth', methods=['POST', 'GET'])
def auth_user():
    if request.method == "GET":
        sess_user = session.get('temp_user_id')
        return ('', 204) if sess_user else jsonify(False)

    # For POST requests, create anonymous user
    return redirect(url_for('auth.create_anonymous_user'))


@auth_bp.route('/logout')
def logout():
    # Clear session and create new anonymous user
    session.clear()
    return redirect(url_for('auth.create_anonymous_user'))
