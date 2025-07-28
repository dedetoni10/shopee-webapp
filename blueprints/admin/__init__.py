# File: blueprints/admin/__init__.py
from flask import Blueprint

# --- PERUBAHAN BARU DI SINI ---
# Pastikan url_prefix adalah '/admin' (tanpa slash di akhir, biasanya)
# Pastikan template_folder menunjuk ke lokasi yang benar
bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates')
# --- AKHIR PERUBAHAN BARU ---

from . import routes # Impor routes setelah Blueprint didefinisikan