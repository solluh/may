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

    # Get SMTP settings for admins
    smtp_settings = {}
    smtp_configured = False
    if current_user.is_admin:
        smtp_settings = {
            'enabled': AppSettings.get('smtp_enabled', 'true'),
            'host': AppSettings.get('smtp_host'),
            'port': AppSettings.get('smtp_port', '587'),
            'username': AppSettings.get('smtp_username'),
            'password': AppSettings.get('smtp_password'),
            'sender': AppSettings.get('smtp_sender'),
            'sender_name': AppSettings.get('smtp_sender_name'),
            'tls': AppSettings.get('smtp_tls', 'true'),
            'ssl': AppSettings.get('smtp_ssl', 'false'),
            'pushover_enabled': AppSettings.get('pushover_enabled', 'false'),
            'pushover_app_token': AppSettings.get('pushover_app_token'),
        }
    smtp_configured = bool(
        AppSettings.get('smtp_enabled', 'true') == 'true' and
        AppSettings.get('smtp_host') and
        AppSettings.get('smtp_username')
    )
    pushover_configured = bool(
        AppSettings.get('pushover_enabled') == 'true' and
        AppSettings.get('pushover_app_token')
    )

    return render_template('auth/settings.html',
                           branding=branding,
                           smtp_settings=smtp_settings,
                           smtp_configured=smtp_configured,
                           pushover_configured=pushover_configured)


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/notifications', methods=['POST'])
@login_required
def notifications():
    """Update user notification preferences"""
    current_user.email_reminders = request.form.get('email_reminders') == 'true'
    current_user.reminder_days_before = int(request.form.get('reminder_days_before', 7))
    current_user.notification_method = request.form.get('notification_method', 'email')
    current_user.webhook_url = request.form.get('webhook_url') or None
    current_user.ntfy_topic = request.form.get('ntfy_topic') or None
    current_user.pushover_user_key = request.form.get('pushover_user_key') or None
    db.session.commit()
    flash('Notification preferences updated', 'success')
    return redirect(url_for('auth.settings') + '#notifications')


@bp.route('/smtp-settings', methods=['POST'])
@login_required
def smtp_settings():
    """Update notification service settings (admin only)"""
    if not current_user.is_admin:
        flash('Access denied', 'error')
        return redirect(url_for('auth.settings'))

    # SMTP settings
    AppSettings.set('smtp_enabled', 'true' if request.form.get('smtp_enabled') else 'false')
    AppSettings.set('smtp_host', request.form.get('smtp_host', ''))
    AppSettings.set('smtp_port', request.form.get('smtp_port', '587'))
    AppSettings.set('smtp_username', request.form.get('smtp_username', ''))
    AppSettings.set('smtp_password', request.form.get('smtp_password', ''))
    AppSettings.set('smtp_sender', request.form.get('smtp_sender', ''))
    AppSettings.set('smtp_sender_name', request.form.get('smtp_sender_name', ''))
    AppSettings.set('smtp_tls', 'true' if request.form.get('smtp_tls') else 'false')
    AppSettings.set('smtp_ssl', 'true' if request.form.get('smtp_ssl') else 'false')

    # Pushover settings
    AppSettings.set('pushover_enabled', 'true' if request.form.get('pushover_enabled') else 'false')
    AppSettings.set('pushover_app_token', request.form.get('pushover_app_token', ''))

    flash('Notification settings updated', 'success')
    return redirect(url_for('auth.settings') + '#notifications')


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
