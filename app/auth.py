from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from app.extensions import db
from app.models import User
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles user login. If the submitted credentials are valid, the user is logged in.
    """
    if request.method == 'POST':
        username = request.form.get('username')  # Retrieve the username from the form
        password = request.form.get('password')  # Retrieve the password from the form

        # Find the user in the database
        user = User.query.filter_by(username=username).first()

        # Validate the user and check password
        if user and check_password_hash(user.password_hash, password):
            if not user.active:
                flash('Your account is inactive. Please contact support.', 'warning')
                return redirect(url_for('auth.login'))

            # Log the user in
            login_user(user)

            # Update the user's last login time
            user.last_login = datetime.utcnow()
            db.session.commit()

            flash('Logged in successfully!', 'success')
            return redirect(url_for('main.index'))  # Redirect to the main page

        # Invalid credentials
        flash('Invalid username or password. Please try again.', 'danger')

    # For GET requests, render the login page
    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """
    Logs out the current user and redirects to the login page.
    """
    logout_user()
    flash('You have successfully logged out.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.before_app_request
def before_request():
    """
    Hook to ensure the user is active before every request.
    Prevents inactive accounts from accessing restricted areas.
    """
    if current_user.is_authenticated and not current_user.active:
        logout_user()
        flash('Your account is inactive. Please contact support.', 'warning')
        return redirect(url_for('auth.login'))
