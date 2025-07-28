from flask import Blueprint

# Inisiasi Blueprint. Parameter pertama adalah nama Blueprint, kedua adalah nama modul.
bp = Blueprint('homepage', __name__, template_folder='templates', static_folder='static')

# Mengimpor rute dari file routes.py agar terdaftar di Blueprint ini
from . import routes