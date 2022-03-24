from __future__ import absolute_import, unicode_literals

import os

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.local')
app = Celery('sherpa')

app.conf.task_routes = {
    # SMS Queue
    'campaigns.tasks.attempt_batch_text': {'queue': 'sms'},
    'markets.tasks.purchase_additional_market_task': {'queue': 'sms'},
    'markets.tasks.update_numbers': {'queue': 'sms'},
    'markets.tasks.update_pending_numbers': {'queue': 'sms'},
    'phone.tasks.purchase_market_numbers': {'queue': 'sms'},
    'phone.tasks.purchase_phone_numbers_task': {'queue': 'sms'},
    'sms.tasks.record_phone_number_auto_dead': {'queue': 'sms'},
    'sms.tasks.record_phone_number_stats_received': {'queue': 'sms'},
    'sms.tasks.sms_message_received': {'queue': 'sms'},
    'sms.tasks.sms_message_received_router': {'queue': 'sms'},
    'sms.tasks.sms_relay_from_rep_task': {'queue': 'sms'},
    'sms.tasks.telnyx_status_callback_task': {'queue': 'sms'},
    'sms.tasks.track_sms_reponse_time_task': {'queue': 'sms'},
    'sms.tasks.update_template_stats': {'queue': 'sms'},
    'sms.tasks.verify_spam_counts': {'queue': 'sms'},

    # Slow Queue
    'billing.tasks.full_sync_to_salesforce': {'queue': 'slow'},
    'companies.tasks.update_churn_stats': {'queue': 'slow'},
    'companies.tasks.upload_internal_dnc_task': {'queue': 'slow'},
    'litigation.tasks.upload_litigator_list_task': {'queue': 'slow'},
    'prospects.tasks.update_prospect_after_create': {'queue': 'slow'},
    'prospects.tasks.update_prospect_async': {'queue': 'slow'},
    'prospects.tasks.upload_prospects_task2': {'queue': 'slow'},
    'prospects.tasks.validate_address_single_task': {'queue': 'slow'},
    'skiptrace.tasks.validate_skip_trace_returned_address_task': {'queue': 'slow'},

    # SkipTrace Queue
    'skiptrace.tasks.gather_daily_skip_trace_stats': {'queue': 'skip_trace'},
    'skiptrace.tasks.send_skip_trace_confirmation_task': {'queue': 'skip_trace'},
    'skiptrace.tasks.send_skip_trace_error_upload_email_task': {'queue': 'skip_trace'},
    'skiptrace.tasks.send_push_to_campaign_confirmation_task': {'queue': 'skip_trace'},
    'skiptrace.tasks.skip_trace_push_to_campaign_task': {'queue': 'skip_trace'},
    'skiptrace.tasks.start_skip_trace_task': {'queue': 'skip_trace'},

    # ES Queue
    'search.tasks.prepare_tags_for_index_update': {'queue': 'es'},
    'search.tasks.stacker_full_update': {'queue': 'es'},
    'search.tasks.stacker_update_address_data': {'queue': 'es'},
    'search.tasks.stacker_update_property_data': {'queue': 'es'},
    'search.tasks.stacker_update_prospect_data': {'queue': 'es'},
    'search.tasks.stacker_update_property_tags': {'queue': 'es'},
}
app.conf.timezone = "US/Mountain"
app.conf.beat_schedule = {
    "run_open_tasks": {
        "task": "sherpa.tasks.run_open_tasks",
        "schedule": 15.0,
    },
    # run every 2 hours during working hours, mon to fri.  0745 EDT - 1645 PDT
    "full_sync_to_salesforce": {
        "task": "billing.tasks.salesforce.full_sync_to_salesforce",
        "schedule": crontab(minute=45, hour='5-17/2', day_of_week='mon-fri'),
    },
    # need to run these before midnight MT
    "directmail_nightlies": {
        "task": "campaigns.tasks.nightly_directmail_tasks",
        "schedule": crontab(minute=0, hour=20),
    },
    # run clear idle queries every minute
    "clear_idle_queries": {
        "task": "sherpa.tasks.clear_idle_queries",
        "schedule": 60.0,
    },
}

# Load django settings with CELERY prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

@setup_logging.connect
def config_loggers(*args, **kwargs):
    from logging.config import dictConfig
    from django.conf import settings
    dictConfig(settings.LOGGING)

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()
