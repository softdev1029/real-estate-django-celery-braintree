import os

from .base import *  # noqa: F401, F403

APP_URL = 'http://localhost:3000'

CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",
    "http://localhost:5000",
]

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
]

# If we're using ngrok, need to add its url into various places.
NGROK_URL = os.getenv('NGROK_URL')

if NGROK_URL:
    ALLOWED_HOSTS = ALLOWED_HOSTS + [NGROK_URL]
    CORS_ORIGIN_WHITELIST = CORS_ORIGIN_WHITELIST + [f'http://{NGROK_URL}']

MIDDLEWARE += ['sherpa.middleware.TimeDelayMiddleware']

INSTALLED_APPS += [
    'django_extensions',
    'silk',
]

DJANGO_API_PROFILING_ENABLED = os.getenv('DJANGO_API_PROFILING_ENABLED')
if DJANGO_API_PROFILING_ENABLED:
    # before any process_request middleware which returns, after gzip
    # security and common only return on request for redirects so we append
    MIDDLEWARE += ['silk.middleware.SilkyMiddleware']

if TEST_MODE:
    REQUEST_TIME_DELAY = 0
else:
    REQUEST_TIME_DELAY = float(os.getenv('REQUEST_TIME_DELAY', 0))

try:
    # Override settings for yourself locally in `core/settings/local_user.py`.
    from .local_user import *
except ImportError:
    pass

TELEPHONY_WEBHOOK_DOMAIN = 'localhost:8000'
