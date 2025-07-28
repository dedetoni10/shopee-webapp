# File: blueprints/apps/app_store/__init__.py
from flask import Blueprint

bp = Blueprint('app_store', __name__, url_prefix='/apps/store', template_folder='templates')

from . import routes