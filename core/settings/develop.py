import os

from .base import *  # noqa: F401, F403


DEBUG = True


CORS_ORIGIN_WHITELIST = [
    'https://app-dev.leadsherpa.com',
]


ALLOWED_HOSTS = [
    'dev.leadsherpa.com',
    'api-dev.leadsherpa.com',
    'api-dev.phonewebhook.com',
]


APP_URL = 'https://app-dev.leadsherpa.com'


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True
EMAIL_HOST = 'email-smtp.us-east-1.amazonaws.com'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'AKIAXIRUHKSI56CHF66C')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_PORT = 587
DEFAULT_FROM_EMAIL = 'Sherpa Develop <sherpa@leadsherpa.com>'

ELASTICSEARCH_HOSTS = ['localhost:9200']

TELEPHONY_WEBHOOK_DOMAIN = 'https://api-dev.phonewebhook.com'
