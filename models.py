# File: models.py
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
import datetime
import secrets
import string

def generate_random_id(length=6):
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for i in range(length))

class User(UserMixin, db.Model):
    id = db.Column(db.String(6), primary_key=True, default=lambda: generate_random_id())
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    
    user_apps = db.relationship('UserApp', backref='user', lazy='dynamic', cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
         return str(self.id)

    def __repr__(self):
        return f'<User {self.username}>'

class App(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(256))
    url = db.Column(db.String(128), unique=True, nullable=False)
    # is_active (DIHAPUS untuk versi ini)
    # prices (DIHAPUS untuk versi ini)

# AppPrice Model (DIHAPUS SEPENUHNYA untuk versi ini)
# class AppPrice(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     app_id = db.Column(db.Integer, db.ForeignKey('app.id'), nullable=False)
#     duration_type = db.Column(db.String(10), nullable=False)
#     duration_hours = db.Column(db.Integer, nullable=False)
#     price = db.Column(db.Float, nullable=False)
#     description = db.Column(db.String(100), nullable=True)
#     __table_args__ = (db.UniqueConstraint('app_id', 'duration_type', name='_app_duration_uc'),)
#     def __repr__(self):
#         return f'<AppPrice App:{self.app_id} Dur:{self.duration_type} Price:{self.price}>'


class UserApp(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(6), db.ForeignKey('user.id'), nullable=False) # PERBAIKAN: Ubah Integer ke String
    app_id = db.Column(db.Integer, db.ForeignKey('app.id'), nullable=False)
    installation_date = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    premium_end_date = db.Column(db.DateTime, nullable=True) 

    __table_args__ = (db.UniqueConstraint('user_id', 'app_id', name='_user_app_uc'),)

    def __repr__(self):
        return f'<UserApp User:{self.user_id} App:{self.app_id}>'