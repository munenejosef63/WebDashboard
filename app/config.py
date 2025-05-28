import os


class Config:
    """
    Base configuration class with default settings for the application.
    """
    SECRET_KEY = os.getenv('SECRET_KEY', 'default-secret-key-4a7d89f3e2b1c05f9e6d8a47')
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:Masterpiece@localhost:5432/excel_dashboard'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True  # Enabled by default but explicit is better

    # File upload configuration
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')  # Default to 'uploads' directory
    ALLOWED_EXTENSIONS = {'csv', 'xls', 'xlsx'}

    # Session management configuration
    SESSION_TYPE = os.getenv('SESSION_TYPE', 'filesystem')  # Default to filesystem session
    SESSION_FILE_DIR = os.getenv('SESSION_FILE_DIR', 'flask_session')  # Directory to store session files
    SESSION_PERMANENT = False

    # Logging configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')  # Default log level is INFO
    LOG_FOLDER = os.getenv('LOG_FOLDER', 'logs')  # Default log storage directory

    # Pagination settings
    ITEMS_PER_PAGE = int(os.getenv('ITEMS_PER_PAGE', 20))  # Default to 20 items per page


    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 10MB limit
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour expiration


class DevelopmentConfig(Config):
    """
    Configuration for development environment.
    """
    DEBUG = True
    SQLALCHEMY_ECHO = True  # Enable SQL statements logging for debugging


class TestingConfig(Config):
    """
    Configuration for testing environment.
    """
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///test.db'  # Use SQLite for testing
    WTF_CSRF_ENABLED = False  # Disable CSRF for easier testing
    SESSION_TYPE = 'null'  # No session persistence during tests


class ProductionConfig(Config):
    """
    Configuration for production environment.
    """
    DEBUG = False
    SESSION_TYPE = os.getenv('SESSION_TYPE', 'filesystem')  # Allow override for production session type
    SESSION_FILE_DIR = os.getenv('SESSION_FILE_DIR', '/var/tmp/flask_sessions')  # Production directory


# Setting up the configuration options to select appropriate configuration
config_options = {
    'default': Config,
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
}
