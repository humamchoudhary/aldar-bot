# from . import chat, admin, auth
from flask import Blueprint

chat_bp = Blueprint('chat', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
auth_bp = Blueprint('auth', __name__)
min_bp = Blueprint('min', __name__, url_prefix='/min')
api_bp = Blueprint('api', __name__, url_prefix='/api')
