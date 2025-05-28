from .models import db, User
from datetime import datetime


def initialize_database(app):
    """Initialize database tables"""
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username='admin').first():
            admin = User(
            )
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()


def clear_database(app):
    """Drop all tables (development only)"""
    with app.app_context():
        db.drop_all()