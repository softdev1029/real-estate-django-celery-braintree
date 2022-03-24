import os

import braintree
import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

from .staging import *  # noqa: F401, F403


DEBUG = False


CORS_ORIGIN_WHITELIST = [
    'https://next.leadsherpa.com',
    'https://app.leadsherpa.com',
]


ALLOWED_HOSTS = [
    'www.leadsherpa.com',
    'app.leadsherpa.com',
    'api.leadsherpa.com',
    'api.phonewebhook.com',
    'legacy.leadsherpa.com',
    'telnyx.leadsherpa.com',
]


DEFAULT_FROM_EMAIL = 'Lead Sherpa <sherpa@leadsherpa.com>'


SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'b7v6)h40xjqv72*vv35e_p*!706bm%57z9ehy9m*#zm#0vr7+t'
)


# legacy: this has already been 12-factored
BRAINTREE_ENV = braintree.Environment.Production
BRAINTREE_MERCHANT_ID = '3sm6qt24mfcgmt34'
BRAINTREE_PUBLIC_KEY = '8hhpbws57354nf55'

USE_TEST_MESSAGING = False


APP_URL = 'https://app.leadsherpa.com'


# Skip trace settings
IDI_CLIENT_ID = 'api-client@snowy2'
IDI_LOGIN_BASE_URL = 'https://login-api.idicore.com/'
IDI_API_BASE_URL = 'https://api.idicore.com/'
SKIP_TRACE_SEND_ERROR_EMAIL = True


# Messaging/Calling settings
TELNYX_CONNECTION_ID = '1303023938833482794'
TELNYX_RELAY_CONNECTIONS = 100


USE_TEST_FRESHSUCCESS = False


ignore_logger("django.security.DisallowedHost")
sentry_sdk.init(
    dsn="https://4d6491febaa0453da31899d3b2244062@sentry.leadsherpa.com/1",
    integrations=[
        DjangoIntegration(),
        CeleryIntegration(),
    ],
    traces_sample_rate = 0.001,
    send_default_pii=True,
)

ELASTICSEARCH_HOSTS = ['192.168.227.159:9200']

TELEPHONY_WEBHOOK_DOMAIN = 'https://api.phonewebhook.com'
