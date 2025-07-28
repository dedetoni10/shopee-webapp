# File: app.py
from flask import Flask, redirect, url_for, flash, request, session # Import session
from flask_login import current_user # Make sure current_user is imported

# Import filter function from extensions
from extensions import db, login_manager, inject_global_template_vars, format_rupiah_no_rp # Ensure format_rupiah_no_rp is imported

# ---- BAGIAN 1: INISIASI APLIKASI DAN EKSTENSI ----
app = Flask(__name__)
app.config['SECRET_KEY'] = 'kunci-rahasia-yang-kuat' 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rumaiku.db'

db.init_app(app)
login_manager.init_app(app)
app.context_processor(inject_global_template_vars) # Ini yang penting!

# --- DAFTARKAN FILTER JINJA2 DI SINI ---
# This line is crucial for registering the filter
app.jinja_env.filters['format_rupiah_no_rp'] = format_rupiah_no_rp

login_manager.login_view = 'auth.login'

@login_manager.unauthorized_handler
def unauthorized():
    flash('Kamu tidak punya hak akses untuk melihat halaman ini.', 'warning')
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('auth.login'))

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(user_id)

# --- Debugging Request Global ---
@app.before_request
def log_request_info():
    if request.method == 'POST':
        print(f"\n--- GLOBAL DEBUG: Incoming POST Request ---")
        print(f"Path: {request.path}")
        print(f"Method: {request.method}")
        print(f"Form Data: {request.form}")
        print(f"Headers: {request.headers}")
        print(f"--- END GLOBAL DEBUG ---\n")
# --- Akhir Debugging ---

# ---- BAGIAN 2: IMPOR DAN DAFTARKAN BLUEPRINT ----
from blueprints.homepage import bp as homepage_bp
from blueprints.dashboard import bp as dashboard_bp
from blueprints.auth import bp as auth_bp
from blueprints.admin import bp as admin_bp
from blueprints.apps.app_store import bp as app_store_bp
from blueprints.apps.calculator_roas import bp as calculator_roas_bp

app.register_blueprint(homepage_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(app_store_bp)
app.register_blueprint(calculator_roas_bp)

# ---- BAGIAN 3: JALANKAN APLIKASI ----
if __name__ == '__main__':
    with app.app_context():
        db.create_all() 
        
        from models import App, User 
        if not App.query.filter_by(name='Kalkulator ROAS').first():
            new_app = App(name='Kalkulator ROAS', description='Hitung Return on Ad Spend (ROAS) untuk kampanye iklanmu.', url='roas_calculator')
            db.session.add(new_app)
            db.session.commit()
            print("Aplikasi 'Kalkulator ROAS' ditambahkan ke database.") 
        else:
            print("Aplikasi 'Kalkulator ROAS' sudah ada di database.") 
        
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', is_admin=True) 
            admin_user.set_password('021212') 
            db.session.add(admin_user)
            db.session.commit()
            print("Pengguna admin dibuat: admin/021212")

    app.run(debug=True)