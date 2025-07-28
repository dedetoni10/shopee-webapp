# File: extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
import datetime
from flask import url_for # Import url_for to build dynamic endpoints

db = SQLAlchemy()
login_manager = LoginManager()

# --- Tambahkan: fungsi filter format_rupiah_no_rp di sini ---
def format_rupiah_no_rp(value):
    """Formats a number as Indonesian Rupiah without the 'Rp' prefix."""
    if value is None:
        return '0'
    try:
        return "{:,.0f}".format(float(value)).replace(",", ".")
    except (ValueError, TypeError):
        return str(value)
# --- Akhir penambahan ---

def inject_global_template_vars():
    # Variabel notifikasi percobaan aplikasi tidak lagi diatur secara global di sini.
    # Mereka akan diatur secara spesifik oleh blueprint aplikasi masing-masing.
    installed_apps_for_sidebar = []
    whatsapp_number = "6281234567890" # Ganti dengan nomor WhatsApp Anda

    if current_user.is_authenticated:
        from models import UserApp, App # Import di dalam fungsi untuk menghindari circular import
        user_app_entries = UserApp.query.filter_by(user_id=current_user.id).all()

        for user_app_entry in user_app_entries:
            app_info = App.query.get(user_app_entry.app_id)
            if app_info:
                # Dapatkan endpoint yang benar untuk aplikasi
                endpoint_name = None
                if app_info.url == 'roas_calculator':
                    endpoint_name = 'calculator_roas.index'
                # Tambahkan kondisi lain di sini untuk aplikasi lain
                # elif app_info.url == 'other_app_url':
                #      endpoint_name = 'other_blueprint.index'

                if endpoint_name:
                    app_details = {
                        'name': app_info.name,
                        'url': app_info.url,
                        'icon': 'default', # Anda bisa menambahkan kolom icon di model App
                        'url_endpoint': endpoint_name # Tambahkan atribut url_endpoint
                    }
                    installed_apps_for_sidebar.append(app_details)

    return dict(
        installed_apps_for_sidebar=installed_apps_for_sidebar,
        whatsapp_number=whatsapp_number
        # Notifikasi aplikasi tidak lagi dikirim secara global
    )

def get_app_trial_status(user_id, app_url):
    """
    Checks the trial/premium status for a specific app for a given user.
    Returns a dictionary with notification details or empty if no notification needed.
    """
    from models import UserApp, App # Import here to avoid circular dependencies
    
    notification_data = {
        'notification_type': None,
        'notification_message_prefix': "",
        'app_name': "",
        'time_remaining_seconds': 0,
        'trial_expired': False,
        'is_premium_active': False
    }
    whatsapp_number = "6289679538444" # Nomor WhatsApp khusus untuk notifikasi trial/expired

    if not user_id:
        return notification_data

    app_info = App.query.filter_by(url=app_url).first()
    if not app_info:
        # Jika aplikasi tidak ditemukan, tidak ada status untuk dilaporkan
        return notification_data

    user_app_entry = UserApp.query.filter_by(user_id=user_id, app_id=app_info.id).first()

    if user_app_entry:
        current_time = datetime.datetime.utcnow()
        
        # 1. Cek status Premium dulu
        if user_app_entry.is_premium and user_app_entry.premium_end_date and user_app_entry.premium_end_date > current_time:
            notification_data['is_premium_active'] = True
            notification_data['notification_type'] = "premium"
            notification_data['app_name'] = app_info.name
            notification_data['time_remaining_seconds'] = (user_app_entry.premium_end_date - current_time).total_seconds()
            notification_data['notification_message_prefix'] = f"Langganan Premium Aplikasi {app_info.name} tersisa: "
        else:
            # 2. Jika bukan premium atau premium sudah berakhir, cek masa percobaan
            trial_duration_hours = 24 # Durasi trial, sesuaikan jika perlu
            trial_end_time = user_app_entry.installation_date + datetime.timedelta(hours=trial_duration_hours)
            
            if current_time < trial_end_time:
                # Masih dalam masa percobaan
                notification_data['trial_expired'] = False
                notification_data['is_premium_active'] = False
                notification_data['notification_type'] = 'trial'
                notification_data['time_remaining_seconds'] = (trial_end_time - current_time).total_seconds()
                notification_data['app_name'] = app_info.name
                notification_data['notification_message_prefix'] = f"Masa percobaan Aplikasi {app_info.name} akan berakhir dalam"
            else:
                # Masa percobaan sudah berakhir
                notification_data['trial_expired'] = True
                notification_data['is_premium_active'] = False
                notification_data['notification_type'] = 'expired'
                notification_data['app_name'] = app_info.name
                notification_data['notification_message_prefix'] = f"Masa percobaan Aplikasi {app_info.name} telah berakhir!"
                notification_data['time_remaining_seconds'] = 0 # Sudah berakhir
    else:
        # Aplikasi belum diinstal oleh user ini, anggap tidak ada notifikasi aktif untuknya
        pass
    
    notification_data['whatsapp_number'] = whatsapp_number
    return notification_data