# File: blueprints/admin/routes.py
from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user
from models import User, App, UserApp # Pertahankan App, UserApp
from extensions import db
import datetime
from functools import wraps
from flask_wtf.csrf import generate_csrf

from . import bp

def admin_required(f):
    @login_required
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('Anda tidak memiliki izin untuk mengakses halaman ini.', 'danger')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/')
@admin_required
def index():
    users = User.query.all()
    # all_apps = App.query.all() # Ini akan dibutuhkan lagi untuk modal grant_access
    all_apps = App.query.all() # KEMBALIKAN: Ambil semua aplikasi
    
    users_data = []
    trial_duration_hours = 24 # Durasi trial default
    for user in users:
        installed_apps_info = []
        user_app_entries = UserApp.query.filter_by(user_id=user.id).all()
        for ua_entry in user_app_entries:
            app_obj = App.query.get(ua_entry.app_id)
            if app_obj:
                status_text = "Trial Aktif"
                is_premium_active = ua_entry.is_premium and ua_entry.premium_end_date and ua_entry.premium_end_date > datetime.datetime.utcnow()
                
                if is_premium_active:
                    time_remaining_seconds = (ua_entry.premium_end_date - datetime.datetime.utcnow()).total_seconds()
                    status_text = f"Premium (Sisa: {int(time_remaining_seconds / 3600)}j)"
                else:
                    time_remaining_seconds = (ua_entry.installation_date + datetime.timedelta(hours=trial_duration_hours) - datetime.datetime.utcnow()).total_seconds()
                    if time_remaining_seconds <= 0:
                        status_text = "Trial Berakhir"
                    else:
                        status_text = f"Trial (Sisa: {int(time_remaining_seconds / 3600)}j)"
                
                installed_apps_info.append({
                    'id': app_obj.id,
                    'name': app_obj.name,
                    'status': status_text,
                    'is_premium': ua_entry.is_premium,
                    'premium_end_date': ua_entry.premium_end_date.strftime('%Y-%m-%d %H:%M') if ua_entry.premium_end_date else '-'
                })
        users_data.append({
            'user': user,
            'installed_apps': installed_apps_info
        })
    return render_template(
        'admin/admin_dashboard.html', 
        users_data=users_data,
        all_apps=all_apps, # KEMBALIKAN: all_apps dikirim untuk modal
        csrf_token=generate_csrf()
    )

# --- BARU: grant_access route dikembalikan ---
@bp.route('/grant_access/<string:user_id>', methods=['POST'])
@admin_required
def grant_access(user_id):
    # Debugging print statements (bisa dihapus nanti setelah berfungsi)
    print(f"\n--- DEBUG: grant_access route called ---")
    print(f"Request Method: {request.method}")
    print(f"Form Data: {request.form}")
    print(f"User ID from URL: {user_id}")

    app_id = request.form.get('app_id', type=int)
    access_type = request.form.get('access_type')
    duration_type = request.form.get('duration_type')
    custom_hours = request.form.get('custom_hours', type=int)

    print(f"DEBUG: app_id={app_id}, access_type={access_type}, duration_type={duration_type}, custom_hours={custom_hours}")

    if not app_id or not access_type:
        print("DEBUG: Data tidak lengkap (app_id atau access_type kosong).")
        flash('Data yang tidak lengkap untuk memberikan akses.', 'danger')
        return redirect(url_for('admin.index'))
    
    user = User.query.get(user_id)
    app = App.query.get(app_id)

    if not user or not app:
        print("DEBUG: Pengguna atau Aplikasi tidak ditemukan (dari DB).")
        flash('Pengguna atau Aplikasi tidak ditemukan.', 'danger')
        return redirect(url_for('admin.index'))

    user_app_entry = UserApp.query.filter_by(user_id=user_id, app_id=app_id).first()
    
    # Jika entri UserApp belum ada, buat yang baru
    if not user_app_entry:
        print(f"DEBUG: Aplikasi (ID: {app_id}) belum diinstal oleh pengguna {user_id}. Membuat instalasi baru.")
        user_app_entry = UserApp(
            user_id=user_id,
            app_id=app_id,
            installation_date=datetime.datetime.utcnow(),
            is_premium=False,
            premium_end_date=None
        )
        db.session.add(user_app_entry)
        db.session.commit()
        print(f"DEBUG: Instalasi baru berhasil dibuat untuk user {user_id} app {app_id}.")
        flash(f'Aplikasi {app.name} berhasil diinstal untuk {user.username}.', 'info')
    
    # Logika berdasarkan Tipe Akses
    if access_type == 'trial':
        user_app_entry.is_premium = False
        user_app_entry.premium_end_date = None
        user_app_entry.installation_date = datetime.datetime.utcnow() # Reset trial timer
        flash(f'Akses percobaan 24 jam untuk {app.name} diberikan kepada {user.username}.', 'success')
        print(f"DEBUG: Memberikan akses TRIAL untuk user {user.username} app {app.name}.")

    elif access_type == 'premium':
        user_app_entry.is_premium = True
        premium_duration_timedelta = datetime.timedelta(hours=0)

        if not duration_type:
            print("DEBUG: Durasi tidak valid untuk premium.")
            flash('Durasi tidak valid untuk akses premium.', 'danger')
            return redirect(url_for('admin.index'))

        if duration_type == '24h':
            premium_duration_timedelta = datetime.timedelta(hours=24)
        elif duration_type == '3d':
            premium_duration_timedelta = datetime.timedelta(days=3)
        elif duration_type == '7d':
            premium_duration_timedelta = datetime.timedelta(days=7)
        elif duration_type == '1m': # 1 month
            premium_duration_timedelta = datetime.timedelta(days=30) 
        elif duration_type == 'custom' and custom_hours is not None and custom_hours > 0:
            premium_duration_timedelta = datetime.timedelta(hours=custom_hours)
        else:
            print("DEBUG: Durasi tidak valid.")
            flash('Durasi tidak valid.', 'danger')
            return redirect(url_for('admin.index'))
        
        current_time = datetime.datetime.utcnow()
        if user_app_entry.premium_end_date and user_app_entry.premium_end_date > current_time:
            user_app_entry.premium_end_date += premium_duration_timedelta
            print(f"DEBUG: Menambahkan durasi premium ke premium_end_date yang ada. New end: {user_app_entry.premium_end_date}")
        else:
            user_app_entry.premium_end_date = current_time + premium_duration_timedelta
            print(f"DEBUG: Mengatur premium_end_date dari sekarang. New end: {user_app_entry.premium_end_date}")
        
        flash(f'Akses premium untuk {app.name} diberikan kepada {user.username} sampai {user_app_entry.premium_end_date.strftime("%Y-%m-%d %H:%M")}!', 'success')
        print(f"DEBUG: Memberikan akses PREMIUM untuk user {user.username} app {app.name}.")
    else:
        print("DEBUG: Tipe akses tidak valid.")
        flash('Tipe akses tidak valid.', 'danger')
        return redirect(url_for('admin.index'))
    
    try:
        db.session.commit()
        print(f"DEBUG: db.session.commit() berhasil!")
        return redirect(url_for('admin.index'))
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Gagal melakukan commit ke database: {e}")
        flash('Terjadi kesalahan saat menyimpan perubahan.', 'danger')
        return redirect(url_for('admin.index'))
# --- AKHIR grant_access route dikembalikan ---


@bp.route('/delete_user/<string:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get(user_id)
    if user and not user.is_admin:
        db.session.delete(user)
        db.session.commit()
        flash(f'Pengguna {user.username} berhasil dihapus.', 'success')
    else:
        flash('Tidak dapat menghapus pengguna ini.', 'danger')
    return redirect(url_for('admin.index'))

@bp.route('/uninstall_app/<string:user_id>/<int:app_id>', methods=['POST'])
@admin_required
def admin_uninstall_app(user_id, app_id):
    user_app_entry = UserApp.query.filter_by(user_id=user_id, app_id=app_id).first()
    user = User.query.get(user_id)
    app = App.query.get(app_id)

    if user_app_entry and user and app:
        db.session.delete(user_app_entry)
        db.session.commit()
        flash(f'Aplikasi {app.name} berhasil dihapus dari pengguna {user.username}.', 'success')
    else:
        flash('Instalasi aplikasi tidak ditemukan.', 'danger')
    return redirect(url_for('admin.index'))

# --- Rute-rute manajemen aplikasi/harga DIHAPUS ---
# app_management route
# add_app route
# ... lainnya