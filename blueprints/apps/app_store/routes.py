# File: blueprints/apps/app_store/routes.py
from flask import render_template, redirect, url_for, flash, request, jsonify # Import jsonify
from flask_login import login_required, current_user
from extensions import db, get_app_trial_status
import datetime

from . import bp
from models import App, UserApp # Import models here to avoid circular dependencies in global scope

@bp.route('/')
@login_required
def index():
    all_apps = App.query.all()
    user_app_entries = UserApp.query.filter_by(user_id=current_user.id).all()

    installed_app_data = {}
    for entry in user_app_entries:
        app_info = App.query.get(entry.app_id)
        if app_info:
            app_status = get_app_trial_status(current_user.id, app_info.url)
            installed_app_data[entry.app_id] = {
                'is_installed': True,
                'trial_expired': app_status['trial_expired'],
                'is_premium_active': app_status['is_premium_active'],
                'whatsapp_number': app_status['whatsapp_number']
            }
        else:
            installed_app_data[entry.app_id] = {
                'is_installed': True,
                'trial_expired': False,
                'is_premium_active': False,
                'whatsapp_number': "6289679538444"
            }

    return render_template(
        'store.html',
        all_apps=all_apps,
        installed_app_data=installed_app_data
    )

@bp.route('/install/<int:app_id>', methods=['GET', 'POST'])
@login_required
def install_app(app_id):
    app_info = App.query.get(app_id)
    if not app_info:
        # Periksa apakah permintaan AJAX untuk mengembalikan JSON error
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Aplikasi tidak ditemukan.', 'category': 'danger'}), 404
        flash('Aplikasi tidak ditemukan.', 'danger')
        return redirect(url_for('app_store.index'))

    user_app_entry = UserApp.query.filter_by(user_id=current_user.id, app_id=app_id).first()

    if request.method == 'POST':
        # Tentukan URL redirect untuk kedua respons (AJAX dan non-AJAX)
        target_redirect_url = url_for('app_store.index') # Default
        if app_info.url == 'roas_calculator':
            target_redirect_url = url_for('calculator_roas.index')
        # Tambahkan URL aplikasi lain jika diperlukan

        if user_app_entry:
            message = f'Aplikasi {app_info.name} sudah terinstal.'
            category = 'info'
            success = True
        else:
            new_user_app = UserApp(
                user_id=current_user.id,
                app_id=app_id,
                is_premium=False,
                premium_end_date=datetime.datetime.utcnow() + datetime.timedelta(days=7)
            )
            db.session.add(new_user_app)
            db.session.commit()
            message = f'Aplikasi {app_info.name} berhasil diinstal dan trial 7 hari diaktifkan!'
            category = 'success'
            success = True
        
        # *** PERBAIKAN PENTING: Mengembalikan JSON untuk permintaan AJAX ***
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': success,
                'message': message,
                'category': category,
                'redirect_url': target_redirect_url
            })
        
        # Untuk permintaan non-AJAX (misalnya, pengiriman form langsung tanpa JS override)
        flash(message, category)
        return redirect(target_redirect_url)

    # Logika untuk menangani permintaan GET (jika user mencoba mengakses /install/1 langsung)
    if user_app_entry:
        flash(f'Aplikasi {app_info.name} sudah terinstal. Anda bisa membukanya dari dashboard atau App Store.', 'info')
        if app_info.url == 'roas_calculator':
             return redirect(url_for('calculator_roas.index'))
        else:
            return redirect(url_for('app_store.index'))
    else:
        if app_info.url == 'roas_calculator':
            return redirect(url_for('calculator_roas.detail', app_url=app_info.url))
        else:
            flash(f'Halaman detail untuk aplikasi ini belum tersedia.', 'info')
            return redirect(url_for('app_store.index'))