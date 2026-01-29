import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import User, AppSettings

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))

        flash('Invalid username or password', 'error')

    return render_template('auth/login.html')


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return render_template('auth/register.html')

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        current_user.language = request.form.get('language', 'en')
        current_user.distance_unit = request.form.get('distance_unit', 'km')
        current_user.volume_unit = request.form.get('volume_unit', 'L')
        current_user.consumption_unit = request.form.get('consumption_unit', 'L/100km')
        current_user.currency = request.form.get('currency', 'USD')

        # Update password if provided
        new_password = request.form.get('new_password')
        if new_password:
            confirm_password = request.form.get('confirm_new_password')
            if new_password != confirm_password:
                flash('Passwords do not match', 'error')
                branding = AppSettings.get_all_branding() if current_user.is_admin else {}
                return render_template('auth/settings.html', branding=branding)
            current_user.set_password(new_password)

        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('auth.settings'))

    branding = AppSettings.get_all_branding() if current_user.is_admin else {}
    return render_template('auth/settings.html', branding=branding)


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/branding', methods=['POST'])
@login_required
def branding():
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('auth.settings'))

    # Save branding settings
    AppSettings.set('app_name', request.form.get('app_name', 'May'))
    AppSettings.set('app_tagline', request.form.get('app_tagline', 'Vehicle Management'))
    AppSettings.set('primary_color', request.form.get('primary_color', '#0284c7'))

    # Handle logo upload
    if 'logo' in request.files:
        file = request.files['logo']
        if file and file.filename and allowed_file(file.filename):
            # Delete old logo
            old_logo = AppSettings.get('logo_filename')
            if old_logo:
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], old_logo)
                if os.path.exists(old_path):
                    os.remove(old_path)

            filename = f"logo_{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
            AppSettings.set('logo_filename', filename)

    flash('Branding settings updated successfully', 'success')
    return redirect(url_for('auth.settings') + '#branding')


@bp.route('/users')
@login_required
def users():
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))

    users = User.query.all()
    return render_template('auth/users.html', users=users)


@bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))

    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f'Admin status updated for {user.username}', 'success')

    return redirect(url_for('auth.users'))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('main.dashboard'))

    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted', 'success')

    return redirect(url_for('auth.users'))
