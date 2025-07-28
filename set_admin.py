from app import app
from extensions import db
from models import User

# Pastikan kode berjalan dalam konteks aplikasi Flask
with app.app_context():
    # Ganti 'nama-penggunamu' dengan username yang kamu daftarkan
    username_to_set_as_admin = 'admin'
    
    user = User.query.filter_by(username=username_to_set_as_admin).first()
    
    if user:
        user.is_admin = True
        db.session.commit()
        print(f"Pengguna '{username_to_set_as_admin}' sekarang adalah admin.")
    else:
        print(f"Pengguna '{username_to_set_as_admin}' tidak ditemukan.")