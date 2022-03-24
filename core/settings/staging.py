import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

from .base import *  # noqa: F401, F403


DEBUG = True if os.getenv('DEBUG') else False


CORS_ORIGIN_WHITELIST = [
    'https://app-staging.leadsherpa.com',
    'https://demo.leadsherpa.com',
]


ALLOWED_HOSTS = [
    'staging.leadsherpa.com',
    'api-staging.leadsherpa.com',
    'api-staging.phonewebhook.com',
]


APP_URL = 'https://app-staging.leadsherpa.com'


EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True
EMAIL_HOST = 'email-smtp.us-east-1.amazonaws.com'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'AKIAXIRUHKSI56CHF66C')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
EMAIL_PORT = 587
DEFAULT_FROM_EMAIL = 'Staging Sherpa <sherpa@leadsherpa.com>'

INSTALLED_APPS += ['silk']

DJANGO_API_PROFILING_ENABLED = os.getenv('DJANGO_API_PROFILING_ENABLED')
if DJANGO_API_PROFILING_ENABLED:
    # before any process_request middleware which returns, after gzip
    # security and common only return on request for redirects so we append
    MIDDLEWARE += ['silk.middleware.SilkyMiddleware']

TELNYX_RELAY_MESSAGING_PROFILE_ID = os.getenv(
    'TELNYX_RELAY_MESSAGING_PROFILE_ID', '4001711c-7bdd-402b-b271-dc0159fb1d93')


EMAIL_ADMIN_ON_FULL_EXPORT = True

ELASTICSEARCH_HOSTS = ['localhost:9200']

TELEPHONY_WEBHOOK_DOMAIN = 'https://api-staging.phonewebhook.com'

ignore_logger("django.security.DisallowedHost")
sentry_sdk.init(
    dsn="https://3dcb87e4b8764ed6a4d38739932462d2@sentry.leadsherpa.com/2",
    integrations=[
        DjangoIntegration(),
        CeleryIntegration(),
    ],
    traces_sample_rate = 0.001,
    send_default_pii=True,
)
