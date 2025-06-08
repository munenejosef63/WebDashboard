from app.extensions import db

def initialize_database(app):
    """Initialize database tables (deprecated - now handled in app factory)"""
    with app.app_context():
        db.create_all()

def clear_database(app):
    """Drop all tables (development only)"""
    with app.app_context():
        db.drop_all()