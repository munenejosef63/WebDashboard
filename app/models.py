from datetime import datetime
from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, not_
from sqlalchemy import Boolean


class User(db.Model, UserMixin):
    """
    Represents a user with login credentials and metadata.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(512), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)

    spreadsheets = db.relationship(
        'Spreadsheet', back_populates='owner', cascade='all, delete-orphan', lazy=True
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User(username={self.username})>'


class Spreadsheet(db.Model):
    """
    Represents a spreadsheet created or managed by a specific user.
    """
    __tablename__ = 'spreadsheets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    owner = db.relationship('User', back_populates='spreadsheets')
    sheets = db.relationship(
        'Sheet', back_populates='spreadsheet', cascade='all, delete-orphan', lazy=True
    )

    def __repr__(self):
        return f'<Spreadsheet(name={self.name}, user_id={self.user_id})>'


class Sheet(db.Model):
    """
    Represents a single sheet within a spreadsheet.
    """
    __tablename__ = 'sheets'

    id = db.Column(db.Integer, primary_key=True)
    spreadsheet_id = db.Column(db.Integer, db.ForeignKey('spreadsheets.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(255), nullable=False)

    # Relationships
    spreadsheet = db.relationship('Spreadsheet', back_populates='sheets')
    links = db.relationship(
        'Link', back_populates='sheet', cascade='all, delete-orphan', lazy=True
    )

    def __repr__(self):
        return f'<Sheet(name={self.name}, spreadsheet_id={self.spreadsheet_id})>'


class Link(db.Model):
    """
    Represents a specific link within a sheet.
    """
    __tablename__ = 'links'

    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('sheets.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    link = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(100), nullable=False)
    pinned = db.Column(db.Boolean, default=False, server_default='false')

    # Relationship
    sheet = db.relationship('Sheet', back_populates='links')

    def __repr__(self):
        return f'<Link(title={self.title}, url={self.link}, status={self.status})>'


def get_quick_stats(user_id):
    total_files = db.session.query(func.count(Spreadsheet.id)).filter_by(user_id=user_id).scalar()

    total_sections = (
        db.session.query(func.count(Sheet.id))
        .join(Spreadsheet, Sheet.spreadsheet_id == Spreadsheet.id)
        .filter(
            Spreadsheet.user_id == user_id,
            not_(Sheet.name.ilike('credentials'))
        )
        .scalar()
    )

    last_upload = (
        db.session.query(func.max(Spreadsheet.created_at))
        .filter(Spreadsheet.user_id == user_id)
        .scalar()
    )

    return {
        "total_files": total_files,
        "total_sections": total_sections,
        "last_upload": last_upload
    }