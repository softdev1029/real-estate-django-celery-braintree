import os

from .base import *  # noqa: F401, F403


DEBUG = True if os.getenv('DEBUG') else False


CORS_ORIGIN_WHITELIST = [
    'https://app-major.leadsherpa.com',
    'https://demo.leadsherpa.com',
]


ALLOWED_HOSTS = [
    'major.leadsherpa.com',
    'api-major.leadsherpa.com',
    'api-major.phonewebhook.com',
]


APP_URL = 'http://app-major.leadsherpa.com'


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True
EMAIL_HOST = 'email-smtp.us-east-1.amazonaws.com'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'AKIAXIRUHKSI56CHF66C')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_PORT = 587
DEFAULT_FROM_EMAIL = 'Major Sherpa <sherpa@leadsherpa.com>'


TELNYX_RELAY_MESSAGING_PROFILE_ID = os.getenv(
    'TELNYX_RELAY_MESSAGING_PROFILE_ID', '4001711c-7bdd-402b-b271-dc0159fb1d93')


EMAIL_ADMIN_ON_FULL_EXPORT = True

ELASTICSEARCH_HOSTS = ['localhost:9200']

TELEPHONY_WEBHOOK_DOMAIN = 'https://api-major.phonewebhook.com'
