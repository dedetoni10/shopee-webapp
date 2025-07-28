from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User
from . import bp

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Cek apakah username sudah ada
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username sudah terdaftar.', 'error')
            return render_template('auth/register.html')
        
        new_user = User(username=username) # ID akan dibuat otomatis
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Registrasi berhasil! Silakan login.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('Username atau password salah.')
            return redirect(url_for('auth.login'))
        login_user(user)
        flash('Login berhasil!')
        return redirect(url_for('dashboard.index'))
    return render_template('auth/login.html')

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Kamu telah keluar.')
    return redirect(url_for('homepage.index'))

@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        new_username = request.form.get('username')
        if new_username:
            current_user.username = new_username
            db.session.commit()
            flash('Profil berhasil diperbarui!')
            return redirect(url_for('auth.edit_profile'))
    return render_template('auth/edit_profile.html')

# Tambahkan rute baru ini untuk halaman profil
@bp.route('/profile')
@login_required
def profile():
    return render_template('profile.html')