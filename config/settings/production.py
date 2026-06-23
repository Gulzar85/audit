import dj_database_url
from .base import *

DEBUG = False

# Database — read from DATABASE_URL env var
DATABASES = {'default': dj_database_url.config(default='sqlite:///db_prod.sqlite3')}
