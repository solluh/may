import os
from pathlib import Path

basedir = Path(__file__).parent.absolute()


APP_VERSION = '0.2.4'
GITHUB_REPO = 'dannymcc/may'


class Config:
    APP_VERSION = APP_VERSION
    GITHUB_REPO = GITHUB_REPO
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f'sqlite:///{basedir}/data/may.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or str(basedir / 'data' / 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
