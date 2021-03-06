"""
Django settings for core project.

Generated by 'django-admin startproject' using Django 1.11.

For more information on this file, see
https://docs.djangoproject.com/en/1.11/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.11/ref/settings/
"""
from datetime import timedelta
from django.utils.log import DEFAULT_LOGGING
import os
import sys

import braintree
import dj_database_url


PRODUCTION = 'production'
STAGING = 'staging'
FEATURE = 'feature'
CI = 'ci'
LOCAL = 'local'

DEPLOY_TARGETS = [
    # after upgrade to 3.8
    PRODUCTION,  # := 'production',
    STAGING,  # := 'staging',
    FEATURE,  # := 'feature',
    CI,  # := 'ci',
    LOCAL,  # := 'local',
]

DEPLOY_TARGET = os.getenv('DEPLOY_TARGET') or STAGING
assert DEPLOY_TARGET.lower() in DEPLOY_TARGETS

DATA_UPLOAD_MAX_MEMORY_SIZE = 50077900

TEST_MODE = sys.argv[1:2] == ['test']

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace('core', '')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.11/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'b(v6)h40xjqv72*vv35e_p*!706bm%s7z9ehy9m*#zm#0vr7+t'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sites',

    'corsheaders',
    'django_celery_results',
    'django_filters',
    'django_celery_beat',
    'django_object_actions',
    'drf_yasg',
    'rest_framework',
    'rest_framework.authtoken',
    'storages',
    'djoser',
    'import_export',
    'rangefilter',

    'accounts',
    'billing',
    'calls',
    'campaigns',
    'companies',
    'markets',
    'litigation',
    'phone',
    'properties',
    'prospects',
    'sherpa',
    'skiptrace',
    'sms',
    'search',
]

SITE_ID = 1
DJOSER_SITE_ID = 2
TELNYX_TELEPHONY_SITE_ID = 3

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'core', 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'sherpa.context_processors.profile',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/1.11/ref/settings/#databases

# PostgreSQL Only
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'postgres',
        'USER': 'postgres',
        'HOST': 'db',
        'PORT': 5432
    }
}

# Elasticsearch Settings
ELASTICSEARCH_HOSTS = ['elasticsearch:9200']

if os.environ.get('DATABASE_URL', False):
    # DATABASE_URL is set on Linode instances to point to deployed db
    DATABASES['default'] = dj_database_url.parse(os.environ.get('DATABASE_URL'))

DATABASES['default']['CONN_MAX_AGE'] = 500

# Password validation
# https://docs.djangoproject.com/en/1.11/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/1.11/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.11/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'core', 'static')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

STATICFILES_STORAGE = 'core.storage.ErrorSquashingStorage'

MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


REST_FRAMEWORK = {
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
    'DEFAULT_RENDERER_CLASSES': (
        'djangorestframework_camel_case.render.CamelCaseJSONRenderer',
        'djangorestframework_camel_case.render.CamelCaseBrowsableAPIRenderer',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'djangorestframework_camel_case.parser.CamelCaseFormParser',
        'djangorestframework_camel_case.parser.CamelCaseMultiPartParser',
        'djangorestframework_camel_case.parser.CamelCaseJSONParser',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.DjangoModelPermissions',
    ),
    'DEFAULT_PAGINATION_CLASS': 'sherpa.pagination.SherpaPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
}

SIMPLE_JWT = {
    'AUTH_HEADER_TYPES': ('Bearer',),
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60 * 12),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}


# Used for Redoc, called swagger due to conventions with drf_ysag package
REQUIRE_DOCS_ADMIN = False

SWAGGER_SETTINGS = {
    'USE_SESSION_AUTH': True,
    'SECURITY_DEFINITIONS': {
        'Basic': {
            'type': 'basic'
        },
        'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header'
        }
    }
}


DJOSER = {
    'USER_ID_FIELD': 'pk',
    'SEND_ACTIVATION_EMAIL': True,
    'ACTIVATION_URL': 'register?uid={uid}&token={token}',
    'PASSWORD_RESET_CONFIRM_URL': 'password-reset?uid={uid}&token={token}',
    'TOKEN_MODEL': None,
    'SERIALIZERS': {
        'user_create': 'accounts.serializers.UserRegistrationSerializer',
        'current_user': 'accounts.serializers.CurrentUserSerializer',
    },
    'EMAIL': {
        'password_reset': 'accounts.email.SherpaPasswordResetEmail',
        'activation': 'accounts.email.SherpaActivationEmail',
    },
    'USERNAME_RESET_SHOW_EMAIL_NOT_FOUND': True,
}


# AWS Service Settings
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', 'AKIAXIRUHKSI4XZHS54G')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', 'sherpa-dev')
AWS_DEFAULT_ACL = None
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_QUERYSTRING_EXPIRE = 604800  # 7 days

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'Local Sherpa <sherpa@leadsherpa.com>'


# Braintree payment gateway settings
BRAINTREE_ENV = os.getenv('BRAINTREE_ENV') or 'sandbox'

if PRODUCTION in (BRAINTREE_ENV.lower(), DEPLOY_TARGET):
    BRAINTREE_ENV = braintree.Environment.Production
    BRAINTREE_MERCHANT_ID = '3sm6qt24mfcgmt34'
    BRAINTREE_PUBLIC_KEY = '8hhpbws57354nf55'
else:
    BRAINTREE_ENV = braintree.Environment.Sandbox
    BRAINTREE_MERCHANT_ID = 'g3hpzw54ymp4n8md'
    BRAINTREE_PUBLIC_KEY = 'dfttqv2cv7bmmpfw'

BRAINTREE_PRIVATE_KEY = os.getenv('BRAINTREE_PRIVATE_KEY')
BRAINTREE_TESTING_ENABLED = False


# User Roles
USER_ROLES = (
    'master_admin',
    'admin',
    'staff',
    'junior_staff',
)


# Messaging settings
USE_TEST_MESSAGING = True

TELNYX_SECRET_KEY = os.getenv('TELNYX_SECRET_KEY')
TELNYX_API_KEY = os.getenv('TELNYX_API_KEY')
TELNYX_CONNECTION_ID = '1302063929538642944'
TELNYX_RELAY_MESSAGING_PROFILE_ID = os.getenv(
    'TELNYX_RELAY_MESSAGING_PROFILE_ID', '37bc298e-6a06-4472-af3e-8b80d31c2379')
TELNYX_RELAY_CONNECTIONS = 16
TELNYX_CREDENTIAL_ID = '76d610a2-3cf1-41a4-a47a-d74867c5134c'

TWILIO_TEST_SID = 'AC69ad8d1a3e9ded3f7f11d029619df871'
TWILIO_TEST_PRIVATE_TOKEN = os.getenv('TWILIO_TEST_PRIVATE_TOKEN')
TWILIO_SID = 'ACae738c5e6aaf12ffa887440a3143e55b'
TWILIO_PRIVATE_TOKEN = os.getenv('TWILIO_PRIVATE_TOKEN')

MESSAGES_PER_PHONE_PER_DAY = 79
MESSAGES_PER_PHONE_PER_DAY_TWILIO = 79

class NEW_MARKET_NUMBER_COUNT:
    DEFAULT = 30
    INTELIQUENT = 5
    EXTRA = 40

BANNED_WORDS = [
    "loan",
    "buds",
    "cannabis",
    "citi",
    "debt",
    "debts",
    "lend",
    "marijuana",
    "viagra",
    "weed",
    "fuck",
    "fucker",
    "shit",
    "ass",
    "asshole",
    "bitch",
    "mortgage",
    "insurance",
]

# These words cannot be allowed during the initial message (templates) but can be used in quick
# replies.
SPAM_WORDS = [
    "apologize",
    "apology",
    "bother",
    "did i reach the right person",
    "do i have the right person",
    "do you happen to know",
    "do you know anyone",
    "excuse me",
    "out of the blue",
    "property records",
    "public records",
    "shot in the dark",
    "sorry",
]

# Direct Mail Settings
YELLOW_LETTER_TOKEN = os.getenv('YELLOW_LETTER_TOKEN')
ACCUZIP_TOKEN = os.getenv('ACCUZIP_TOKEN')

# Use redis from localhost if not set in environment variable.
REDIS_URL = os.environ['REDIS_URL']

# Celery settings
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_SOFT_TIME_LIMIT=os.getenv('CELERY_TASK_SOFT_TIME_LIMIT')
CELERY_TASK_TIME_LIMIT=os.getenv('CELERY_TASK_TIME_LIMIT')

# for now, only enable results backend explicitly
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_RESULT_EXTENDED = True  # extended result data, overrides default of false
CELERY_RESULT_EXPIRES = 14400  # four hours, overrides default of one day

# Skip trace settings
IDI_CLIENT_ID = 'api-client@snowy2_test'
IDI_CLIENT_SECRET = os.getenv('IDI_CLIENT_SECRET')
IDI_LOGIN_BASE_URL = 'https://login-api-test.idicore.com/'
IDI_API_BASE_URL = 'https://api-test.idicore.com/'


# Skip Trace Credit settings
MIN_CREDIT = 40
SHERPA_CREDITS_CHARGE = .25
SKIP_TRACE_SEND_ERROR_EMAIL = False
MIN_SKIP_TRACE_CHARGE = 2


# Prospect settings
MIN_UPLOAD_CHARGE = 1
PROSPECT_SERVICE_URL = 'http://45.79.39.35:5000/'


# Freshsuccess settings.
FRESHSUCCESS_API_KEY = os.getenv('FRESHSUCCESS_API_KEY')
USE_TEST_FRESHSUCCESS = True
SUCCESS_ADMIN_EMAIL = 'amber@leadsherpa.com'
EMAIL_ADMIN_ON_FULL_EXPORT = False


# Google API credentials
GOOGLE_STREET_VIEW_API_KEY = os.getenv('GOOGLE_STREET_VIEW_API_KEY')
GOOGLE_STREET_VIEW_SECRET = os.getenv('GOOGLE_STREET_VIEW_SECRET')

# Telephony Webhook Endpoint
TELEPHONY_WEBHOOK_DOMAIN = 'localhost:8000'

# Podio credentials
PODIO_CLIENT_ID = os.getenv('PODIO_CLIENT_ID')
PODIO_CLIENT_SECRET = os.getenv('PODIO_CLIENT_SECRET')
SHERPA_FIELDS_MAPPING = [
    {"label": "First Name", "value": "first_name", "example": "John"},
    {"label": "Last Name", "value": "last_name", "example": "Doe"},
    {"label": "Campaign Name", "value": "campaign_name", "example": "My Example Campaign"},
    {"label": "Property Address", "value": "address_address", "example": "123 Main St"},
    {"label": "Property City", "value": "address_city", "example": "San Francisco"},
    {"label": "Property State", "value": "address_state", "example": "CA"},
    {"label": "Property ZIP", "value": "address_zip", "example": "95555"},
    {"label": "Mailing Address", "value": "mailing_address", "example": "123 Main St"},
    {"label": "Mailing City", "value": "mailing_city", "example": "San Francisco"},
    {"label": "Mailing State", "value": "mailing_state", "example": "CA"},
    {"label": "Mailing ZIP", "value": "mailing_zip", "example": "95555"},
    {"label": "Validated Mailing Address", "value": "validated_mailing_address", "example": "123 Main St, San Francisco, CA, 95555"},
    {"label": "Golden Address", "value": "golden_address", "example": ""},
    {"label": "Custom 1", "value": "custom_1", "example": "custom 1"},
    {"label": "Custom 2", "value": "custom_2", "example": "custom 2"},
    {"label": "Custom 3", "value": "custom_3", "example": "custom 3"},
    {"label": "Custom 4", "value": "custom_4", "example": "custom 4"},
    {"label": "Owner Name", "value": "owner_1_name", "example": "John Doe"},
    {"label": "Phone", "value": "phone_1", "example": "(123) 456-7890"},
    {"label": "Phone Type", "value": "phone_1_type", "example": "mobile"},
    {"label": "Lead Stage", "value": "lead_stage", "example": "Follow-up"},
    {"label": "Owner Verified Status", "value": "owner_1_verified_status", "example": "verified"},
    {"label": "Email 1", "value": "email_1", "example": "JohnDoe@gmail.com"},
    {"label": "Last Seen", "value": "email_1_last_seen", "type": "date", "example": "02-22-2020"},
    {"label": "Email 2", "value": "email_2", "example": "JohnDoe@gmail.com"},
    {"label": "Last Seen", "value": "email_2_last_seen", "type": "date", "example": "02-22-2020"},
    {"label": "Alternate Names", "value": "alternate_names", "example": "Mr.Doe"},
    {"label": "Vacancy", "value": "vacancy", "example": "Y"},
    {"label": "IP Address", "value": "ip_address", "example": "192.168.0.1"},
    {"label": "Age", "value": "age", "example": "21"},
    {"label": "Is Deceased", "value": "is_deceased", "example": "No"},
    {"label": "Bankruptcy", "value": "bankruptcy", "example": "02-22-2020"},
    {"label": "Foreclosure", "value": "foreclosure", "type": "date", "example": "02-22-2020"},
    {"label": "Lien", "value": "lien", "type": "date", "example": "02-22-2020"},
    {"label": "Judgment", "value": "judgment", "type": "date", "example": "02-22-2020"},
    {"label": "Relative 1 Name", "value": "relative_1_name", "example": "Kevin Doe"},
    {"label": "Relative 1 Number", "value": "relative_1_numbers", "example": "(123) 456-7890"},
    {"label": "Relative 2 Name", "value": "relative_2_name", "example": "Sarah Doe"},
    {"label": "Relative 2 Number", "value": "relative_2_numbers", "example": "(123) 456-7890"},
    {"label": "Litigator", "value": "litigator", "example": "False"},
    {"label": "Pushed to Campaign", "value": "pushed_to_campaign", "example": "True"},
    {"label": "Skip Traced Date", "value": "skip_trace_date", "type": "date", "example": "02-22-2020"},
    {"label": "Agent", "value": "agent", "example": "John Smith"},
    {"label": "Legal Description", "value": "legal_description", "example": "DENVER MANOR CONDOMINIUMS BLDG 6 UNIT 941 & UND .460 INT IN COMMON AREA"},
    {"label": "Year Built", "value": "year_built", "example": "2000"},
    {"label": "Deed Last Sale Date", "value": "deed_last_sale_date", "type": "date", "example": "02-22-2020"},
    {"label": "Deed Last Sale Price", "value": "deed_last_sale_price", "type" : "number", "example": "$123456"},
    {"label": "Area Gross", "value": "area_gross", "type" : "number", "example": "960"},
    {"label": "Bath Count", "value": "bath_count", "type" : "number", "example": "3"},
    {"label": "Bath Partial Count", "value": "bath_partial_count", "type" : "number", "example": "2"},
    {"label": "Bedrooms Count", "value": "bedrooms_count", "type" : "number", "example": "5"},
    {"label": "Current First Open Loan", "value": "cur_first_position_open_loan_amount", "type" : "number", "example": "123456"},
    {"label": "Available Equity", "value": "available_equity", "type" : "number", "example": "$35,900"},
    {"label": "Quit Claim Flag", "value": "quitclaim_flag", "type" : "number", "example": "12"},
    {"label": "Transfer Amount", "value": "transfer_amount", "type" : "number", "example": "$1234"},
    {"label": "Grantor First Name", "value": "grantor_1name_first", "example": "John"},
    {"label": "Grantor Last Name", "value": "grantor_1name_last", "example": "Doe"},
    {"label": "Sherpa Conversation Link", "value": "sherpa_url", "example": "https://leadsherpa.com/"},
    {"label": "Public Conversation Link", "value": "public_url", "example": "https://leadsherpa.com/"},
    {"label": "Notes", "value": "notes", "example": "example notes"},
    {"label": "Tags", "value": "tags", "example": "Probate / Death"},
]
PODIO_EXAMPLE_PROSPECT = {
    "first_name" : "John",
    "last_name" : "Doe",
    "campaign_name" : "My Example Campaign",
    "tags" : "Probate / Death",
    "public_url" : "https://leadsherpa.com/",
    "sherpa_url" : "https://leadsherpa.com/",
    "notes" : "example notes",
    "address_address" : "123 Main St",
    "address_city" : "San Francisco",
    "address_state" : "CA",
    "address_zip" : "95555",
    "mailing_address" : "123 Main St",
    "mailing_city" : "San Francisco",
    "mailing_state" : "CA",
    "mailing_zip" : "95555",
    "legal_description" : "DENVER MANOR CONDOMINIUMS BLDG 6 UNIT 941 & UND .460 INT IN COMMON AREA",
    "year_built" : "2000",
    "deed_last_sale_date" : "2020-02-22",
    "deed_last_sale_price" : "123456",
    "area_gross" : "960",
    "bath_count" : "3",
    "bath_partial_count" : "2",
    "bedrooms_count" : "5",
    "cur_first_position_open_loan_amount" : "123456",
    "available_equity" : "35900",
    "quitclaim_flag" : "12",
    "transfer_amount" : "1234",
    "grantor_1name_first" : "John",
    "grantor_1name_last" : "Doe",
    "owner_1_name" : "John Doe",
    "phone_1" : "(123) 456-7890",
    "phone_1_type" : "mobile",
    "lead_stage" : "Follow-up",
    "owner_1_verified_status" : "verified",
    "custom_1" : "custom 1",
    "custom_2" : "custom 2",
    "custom_3" : "custom 3",
    "custom_4" : "custom 4",
    "validated_mailing_address" : "123 Main St, San Francisco, CA, 95555",
    "golden_address" : "123 Main St, San Francisco, CA, 95555",
    "last_seen_1" : "3036591069",
    "email_1" : "JohnDoe@gmail.com",
    "email_1_last_seen" : "2020-02-22",
    "email_2" : "JohnDoe@gmail.com",
    "email_2_last_seen" : "2020-02-22",
    "alternate_names" : "Mr.Doe",
    "vacancy" : "Y",
    "ip_address" : "192.168.0.1",
    "age" : "21",
    "is_deceased" : "No",
    "bankruptcy" : "2020-02-22",
    "foreclosure" : "2020-02-22",
    "lien" : "2020-02-22",
    "judgment" : "2020-02-22",
    "relative_1_name" : "Kevin Doe",
    "relative_1_numbers" : "(123) 456-7890",
    "relative_2_name" : "Sarah Doe",
    "relative_2_numbers" : "(123) 456-7890",
    "litigator" : "False",
    "pushed_to_campaign" : "True",
    "skip_trace_date" : "2020-02-22",
    "agent" : "John Smith"
}

# Django Cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# Direct mail Post card price
POST_CARD_DISCOUNT_PRICE = 0.44

# Direct Mail Discount period
DISCOUNT_START_DATE = "03-31-2021"  # Date format("mm-dd-yyyy")
DISCOUNT_END_DATE = "08-28-2021"

UPLOAD_PROCESSING_BATCH_LIMIT = 50

# Salesforce Settings
SALESFORCE_DOMAIN = os.getenv('SALESFORCE_DOMAIN') or (
    None if DEPLOY_TARGET == PRODUCTION else 'test'
)
SALESFORCE_USERNAME = ''.join((
    'dev@leadsherpa.com', '.dev' if SALESFORCE_DOMAIN == 'test' else '')
)
# TODO: re-12-factor
SALESFORCE_PASSWORD = 'pqEX%B%BAW2M+iD'  # os.environ['SALESFORCE_PASSWORD']
SALESFORCE_SECURITY_TOKEN = 'Db5ZbMjIF7BIrfnWsrJEuxxBD'  # os.environ['SALESFORCE_SECURITY_TOKEN']

# logging configuration will be merged with default so only put adds/changes here
LOGGING = DEFAULT_LOGGING
LOGGING['loggers']['django']['level'] = os.getenv('DJANGO_LOG_LEVEL', 'INFO')

if DEPLOY_TARGET not in (CI, LOCAL):
    LOGGING['formatters']['syslog'] = {
        'format': '[{levelname}]({name})> {message}',
        'style': '{',
    }
    LOGGING['handlers']['syslog'] = {
        'level': 'INFO',
        'filters': ['require_debug_false'],
        'class': 'logging.handlers.SysLogHandler',
        'formatter': 'syslog',
        'address': ('logs.papertrailapp.com', 15976),
    }
    for logger in LOGGING['loggers'].values():
        logger['handlers'].append('syslog')

for logging_namespace in ('root', 'sherpa', 'celery'):
    LOGGING['loggers'][logging_namespace] = LOGGING['loggers']['django'].copy()

# Microservices settings
INTELIQUENT_MICROSERVICE_URL = os.environ.get('INTELIQUENT_MICROSERVICE_URL')
