from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# Create SQLAlchemy instance
db = SQLAlchemy()

# Login manager
login_manager = LoginManager()
