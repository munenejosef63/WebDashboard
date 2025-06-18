from flask import Flask
from flask_session import Session
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from app.extensions import db, login_manager
from app.config import config_options
from dotenv import load_dotenv
import os

csrf = CSRFProtect()


def create_app(config_name='default'):
    # Load environment variables first
    load_dotenv()

    # Create Flask app instance
    app = Flask(__name__)

    # Load configuration
    app.config.from_object(config_options[config_name])

    # Ensure secret key is set for CSRF and session security
    if not app.config.get('SECRET_KEY'):
        raise ValueError("SECRET_KEY must be set in configuration")

    # Initialize CSRF protection
    csrf.init_app(app)

    # Configure session storage
    if app.config.get('SESSION_TYPE') == 'filesystem':
        session_dir = app.config.get('SESSION_FILE_DIR')
        os.makedirs(session_dir, exist_ok=True)
    Session(app)

    # Initialize database
    db.init_app(app)
    migrate = Migrate(app, db)

    # Configure login manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.session_protection = "basic"

    # Custom Jinja filter - fixed variable shadowing
    @app.template_filter('datetimeformat')
    def datetime_format(value, date_format='%Y-%m-%d %H:%M'):
        return value.strftime(date_format) if value else ""

    # User loader callback
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        try:
            return User.query.get(int(user_id))
        except Exception as e:
            app.logger.error(f"User loader error: {str(e)}")
            return None

    # Register blueprints
    from app.routes import main_bp
    from app.auth_routes import auth_bp
    from app.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    # Create database tables
    with app.app_context():
        db.create_all()
        app.logger.debug("Database tables created (if needed)")

        # Create admin user if doesn't exist
        from app.models import User
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin')
            admin.set_password('munene1234')
            db.session.add(admin)
            db.session.commit()
            app.logger.info("Created admin user: admin/admin")

    return app