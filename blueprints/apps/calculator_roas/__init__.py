# File: blueprints/apps/calculator_roas/__init__.py
from flask import Blueprint

# --- PERUBAHAN DI SINI: url_prefix dan template_folder ---
# url_prefix sekarang relatif terhadap 'apps' (jika apps itu sendiri tidak punya prefix)
# tapi karena app_store punya '/apps/store', ini jadi '/apps/calculator_roas'
bp = Blueprint('calculator_roas', __name__, url_prefix='/apps/calculator_roas', template_folder='templates')
# --- AKHIR PERUBAHAN ---

from . import routes