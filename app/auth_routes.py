from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import SQLAlchemyError
from datetime import timedelta
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Create a blueprint for authentication routes
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login by verifying credentials and starting a session.
    Redirects authenticated users to the dashboard.
    """
    if current_user.is_authenticated:
        logger.info(f"User {current_user.username} is already authenticated. Redirecting to the dashboard.")
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        logger.info(f"Login attempt for username: {username}")

        try:
            # Modified query: removed uploaded_files eager-loading
            user = User.query.options(
                joinedload(User.spreadsheets)  # Kept spreadsheets relationship
            ).filter_by(username=username).first()

            # Verify user credentials
            if user and user.check_password(password):
                # Set session to permanent and configure timeout
                session.permanent = True
                session_timeout = timedelta(minutes=15)  # 15 minute session timeout

                login_user(user)
                logger.info(f"Login successful for user: {username}")
                flash("Login successful!", "success")
                return redirect(url_for('main.dashboard'))
            else:
                logger.warning(f"Failed login attempt for username: {username}")
                flash("Invalid username or password.", "danger")

        except SQLAlchemyError as e:
            logger.error(f"SQLAlchemy error during login for username {username}: {e}")
            flash("A database error occurred. Please try again.", "danger")
            db.session.rollback()
        except Exception as e:
            logger.error(f"Unexpected error during login for username {username}: {e}", exc_info=True)
            flash("An unexpected error occurred. Please try again later.", "danger")
            db.session.rollback()

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """
    Logs out the current user and redirects to the login page with a success message.
    """
    try:
        username = current_user.username
        logout_user()
        logger.info(f"User {username} logged out successfully.")
        flash("You have been logged out.", "info")
    except Exception as e:
        logger.error(f"Error occurred during logout: {e}", exc_info=True)
        flash("An error occurred while logging out. Please try again.", "danger")

    return redirect(url_for('auth.login'))


@auth_bp.route('/extend_session', methods=['POST'])
@login_required
def extend_session():
    """
    Extends the current user's session by resetting the timeout.
    Called via AJAX from the session timeout warning modal.
    """
    try:
        # Reset the session lifetime
        session.permanent = True
        session_timeout = timedelta(minutes=15)  # Reset to 15 minutes

        # For Flask-Login users, this will refresh the session
        if current_user.is_authenticated:
            login_user(current_user, remember=True)

        logger.info(f"Session extended for user: {current_user.username}")
        return jsonify({'status': 'success', 'message': 'Session extended'})

    except Exception as e:
        logger.error(f"Error extending session for user {current_user.username}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Failed to extend session'}), 500