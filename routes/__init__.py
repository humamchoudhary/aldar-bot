# from . import chat, admin, auth
from flask import Blueprint

chat_bp = Blueprint('chat', __name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
auth_bp = Blueprint('auth', __name__)
min_bp = Blueprint('min', __name__, url_prefix='/min')
call_bp = Blueprint('call', __name__, url_prefix='/call')
api_bp = Blueprint('api', __name__, url_prefix='/api')
wa_bp = Blueprint("wa",__name__,url_prefix="/wa")
fb_bp = Blueprint("fb",__name__,url_prefix="/fb")
