from flask import Flask, request, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_babel import Babel, gettext as _
from config import Config
import os

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'
babel = Babel()

# Supported languages
LANGUAGES = {
    'en': 'English',
    'de': 'Deutsch',
    'es': 'Español',
    'fr': 'Français',
    'it': 'Italiano',
    'nl': 'Nederlands',
    'pt': 'Português',
    'pl': 'Polski',
    'sv': 'Svenska',
    'da': 'Dansk',
    'no': 'Norsk',
    'fi': 'Suomi',
    'ja': '日本語',
    'zh': '中文',
    'ko': '한국어'
}


def get_locale():
    """Select the best language for the user"""
    # If user is logged in and has a language preference, use it
    if current_user.is_authenticated and current_user.language:
        return current_user.language

    # Otherwise, try to match browser language
    return request.accept_languages.best_match(LANGUAGES.keys(), default='en')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Babel configuration
    app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    app.config['BABEL_SUPPORTED_LOCALES'] = list(LANGUAGES.keys())

    # Ensure data directories exist
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    from app.models import User, AppSettings

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Make languages and branding available in templates
    @app.context_processor
    def inject_globals():
        branding = AppSettings.get_all_branding()
        return {
            'LANGUAGES': LANGUAGES,
            'APP_NAME': branding.get('app_name', 'May'),
            'APP_TAGLINE': branding.get('app_tagline', 'Vehicle Management'),
            'APP_LOGO': branding.get('logo_filename'),
            'PRIMARY_COLOR': branding.get('primary_color', '#0284c7'),
        }

    from app.routes import main, auth, vehicles, fuel, expenses, api, reminders
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(vehicles.bp)
    app.register_blueprint(fuel.bp)
    app.register_blueprint(expenses.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(reminders.bp)

    with app.app_context():
        db.create_all()
        # Create default admin user if no users exist
        if User.query.count() == 0:
            admin = User(username='admin', email='admin@example.com', is_admin=True)
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()

    return app
