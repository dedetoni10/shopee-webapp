# File: populate_db.py

# Impor app dari file app.py kita
from app import app
from extensions import db
from models import App, User

print("Memulai pengisian database...")

# Menggunakan 'with app.app_context()' untuk memastikan kode berjalan dalam konteks aplikasi Flask
with app.app_context():
    # Periksa apakah tabel App sudah berisi data
    if App.query.count() == 0:
        print("Tabel App kosong. Menambahkan data awal...")
        # Data aplikasi yang akan kita tambahkan
        apps_to_add = [
            App(name='Kalkulator ROAS', description='Hitung ROI dari iklan Shopee kamu.', url='/roas/calculator'),
            App(name='Strategi Iklan Otomatis', description='Otomatisasi bid dan strategi iklan.', url='/ads/strategy'),
            App(name='Analitik Produk', description='Lacak performa produk dan tren pasar.', url='/product/analytics')
        ]
        
        # Tambahkan semua aplikasi ke sesi dan simpan ke database
        db.session.add_all(apps_to_add)
        db.session.commit()
        print("Data App berhasil ditambahkan!")
    else:
        print("Tabel App sudah berisi data. Tidak ada yang ditambahkan.")

print("Selesai.")