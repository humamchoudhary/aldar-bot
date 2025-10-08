# decorators.py
from functools import wraps
from flask import session, request, redirect, url_for, current_app
from services.admin_service import AdminService

def admin_required(roles=None):
    """Decorator to check admin permissions with role-based access"""
    if roles is None:
        roles = ['admin', 'superadmin']
    elif isinstance(roles, str):
        roles = [roles]

    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if user is logged in as admin
            if not session.get('admin_id'):
                session['next'] = request.path
                return redirect(url_for('admin.login'))

            # Get current admin from database
            admin_service = AdminService(current_app.db)
            current_admin = admin_service.get_admin_by_id(session['admin_id'])

            if not current_admin or not current_admin.has_permission(roles):
                return redirect(url_for('admin.login'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper
