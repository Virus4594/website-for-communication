import os
from datetime import timedelta

class Config:
    # Безопасность
    SECRET_KEY = os.environ.get('ViRuS4594VS4594') or os.urandom(32)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_SECRET_KEY = "ViRuS4594VS4594"
    # База данных
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///KDF.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Сессия
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # True в продакшене
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Ограничения
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    UPLOAD_FOLDER = 'static/uploads'
    
    # WebSocket
    SOCKETIO_ASYNC_MODE = 'eventlet'
    
    # Двухфакторная аутентификация
    OTP_SECRET_LENGTH = 32