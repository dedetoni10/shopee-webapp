from flask import render_template
from . import bp # Mengimpor objek Blueprint yang sudah kita buat

# Menggunakan Blueprint untuk mendefinisikan rute
@bp.route('/')
def index():
    return render_template('homepage/index.html')