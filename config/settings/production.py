import os
import dj_database_url
from .base import *

DEBUG = False

# Database — read from DATABASE_URL env var
DATABASES = {'default': dj_database_url.config(default='sqlite:///db_prod.sqlite3')}

# Email — SMTP via environment variables
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'audit@mcdonalds.pk')

# ---------------
# Security Settings for Production
# ---------------

# HTTPS/TLS Enforcement
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True') == 'True'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True') == 'True'
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True') == 'True'

# Cookie Security
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True') == 'True'
SESSION_COOKIE_HTTPONLY = os.getenv('SESSION_COOKIE_HTTPONLY', 'True') == 'True'
SESSION_COOKIE_SAMESITE = 'Strict'

CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True') == 'True'
CSRF_COOKIE_HTTPONLY = os.getenv('CSRF_COOKIE_HTTPONLY', 'True') == 'True'
CSRF_COOKIE_SAMESITE = 'Strict'

# Frame Security
X_FRAME_OPTIONS = 'DENY'

# Content Security
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Referrer Policy
SECURE_REFERRER_POLICY = 'same-origin'

# Permissions Policy (formerly Feature Policy)
PERMISSIONS_POLICY = {
    'accelerometer': [],
    'camera': [],
    'geolocation': [],
    'gyroscope': [],
    'magnetometer': [],
    'microphone': [],
    'payment': [],
    'usb': [],
}

# Content Security Policy
SECURE_CONTENT_SECURITY_POLICY = {
    'default-src': ("'self'",),
    'script-src': (
        "'self'",
        "https://cdn.tailwindcss.com",
        "https://cdn.jsdelivr.net",
        "https://fonts.googleapis.com",
    ),
    'style-src': (
        "'self'",
        "'unsafe-inline'",  # Tailwind requires this - minimize in future
        "https://fonts.googleapis.com",
    ),
    'font-src': (
        "'self'",
        "https://fonts.gstatic.com",
    ),
    'img-src': ("'self'", "data:", "https:"),
    'connect-src': ("'self'",),
    'frame-ancestors': ("'none'",),
    'base-uri': ("'self'",),
    'form-action': ("'self'",),
}

# Admin URL Protection - change from default /admin/
ADMIN_URL = os.getenv('ADMIN_URL', 'secret-admin-panel-' + os.getenv('ADMIN_TOKEN', '').replace(' ', '')[:16] + '/')

# Session Configuration
SESSION_COOKIE_AGE = 3600  # 1 hour
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = False  # Reduce database hits

# Password Hashing - explicitly set strong hasher
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]

# Validate required environment variables at startup
REQUIRED_ENV_VARS = ['SECRET_KEY', 'ALLOWED_HOSTS', 'ADMIN_TOKEN']
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        raise ValueError(f"Environment variable {var} is not set in production!")
