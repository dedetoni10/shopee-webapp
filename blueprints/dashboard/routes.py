# File: blueprints/dashboard/routes.py
from flask import render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from models import App, UserApp
import datetime

from . import bp

@bp.route('/dashboard')
@login_required
def index():
    user_app_entries = UserApp.query.filter_by(user_id=current_user.id).all()
    
    installed_apps_with_details = []
    trial_duration_hours = 24

    for user_app_entry in user_app_entries:
        app_info = App.query.get(user_app_entry.app_id)
        if app_info:
            time_remaining_seconds = 0
            
            # Logika Prioritas Waktu Premium
            if user_app_entry.is_premium and user_app_entry.premium_end_date and user_app_entry.premium_end_date > datetime.datetime.utcnow():
                time_remaining_seconds = (user_app_entry.premium_end_date - datetime.datetime.utcnow()).total_seconds()
            else:
                trial_end_time = user_app_entry.installation_date + datetime.timedelta(hours=trial_duration_hours)
                time_remaining_seconds = (trial_end_time - datetime.datetime.utcnow()).total_seconds()

            if time_remaining_seconds < 0:
                time_remaining_seconds = 0
            
            installed_apps_with_details.append({
                'app': app_info,
                'time_remaining_seconds': int(time_remaining_seconds)
            })

    # Pastikan `installed_apps_for_sidebar` dikelola oleh `inject_global_template_vars`
    # sehingga tidak perlu diteruskan secara eksplisit di sini kecuali ada kebutuhan khusus
    return render_template(
        'dashboard/dashboard.html',
        installed_apps=installed_apps_with_details
    )