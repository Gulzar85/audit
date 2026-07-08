from .base import *

DEBUG = True

ENVIRONMENT = 'development'

ALLOWED_HOSTS = ['*']

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'OPTIONS': {
            'timeout': 20,
        },
    }
}

# Email — print to console for dev
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
