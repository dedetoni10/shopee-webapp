# File: blueprints/dashboard/__init__.py
from flask import Blueprint

bp = Blueprint('dashboard', __name__, template_folder='templates')

# Penting: Baris ini HARUS ADA dan tidak boleh diubah
from . import routes