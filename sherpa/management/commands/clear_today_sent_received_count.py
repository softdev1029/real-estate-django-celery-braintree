from datetime import datetime, timedelta

import braintree

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from accounts.tasks import modify_freshsuccess_user
from campaigns.models import CampaignAggregatedStats
from campaigns.tasks import set_daily_campaign_stats
from companies.tasks import (
    modify_freshsuccess_account,
    process_cancellation_requests,
    release_cancelled_numbers,
    reset_monthly_upload_count,
    update_churn_stats,
    update_monthly_upload_limit_task,
)
from phone.tasks import (
    release_inactive_phone_numbers, update_delivery_rate, update_sherpa_delivery_rate)
from properties.tasks import validate_addresses
from sherpa.models import Company, Market, PhoneNumber
from sherpa.tasks import s3_cleanup_routine
from skiptrace.tasks import gather_daily_skip_trace_stats
from sms.models import DailySMSHistory
from sms.tasks import update_template_stats


braintree.Configuration.configure(
    settings.BRAINTREE_ENV,
    merchant_id=settings.BRAINTREE_MERCHANT_ID,
    public_key=settings.BRAINTREE_PUBLIC_KEY,
    private_key=settings.BRAINTREE_PRIVATE_KEY,
)


class Command(BaseCommand):
    """
    Calls all of our nightly jobs in a cron job at 3am EST.
    """
    def handle(self, *args, **options):
        # Reset daily accumlation data.
        PhoneNumber.objects.filter(total_sent_today__gt=0).update(total_sent_today=0)
        CampaignAggregatedStats.objects.filter(
            Q(total_intial_sms_sent_today_count__gt=0),
        ).update(total_intial_sms_sent_today_count=0)
        Company.objects.filter(
            Q(total_intial_sms_sent_today_count__gt=0),
        ).update(total_intial_sms_sent_today_count=0)
        Market.objects.filter(
            Q(total_intial_sms_sent_today_count__gt=0),
        ).update(total_intial_sms_sent_today_count=0)

        if settings.TEST_MODE:
            # Should test the below tasks separately, but still want to test this command to catch
            # import errors.
            return

        # Call long running nightly tasks
        reset_monthly_upload_count.delay()
        release_inactive_phone_numbers.delay()
        update_monthly_upload_limit_task.delay()
        update_churn_stats.delay()
        process_cancellation_requests.delay()
        release_cancelled_numbers.delay()
        update_delivery_rate.delay()
        update_sherpa_delivery_rate.delay()
        s3_cleanup_routine.delay()
        update_template_stats.delay()
        validate_addresses.delay()

        yesterday = datetime.today().date() - timedelta(days=1)
        yesterday_str = yesterday.strftime("%Y-%m-%d")
        set_daily_campaign_stats.delay(yesterday_str)
        gather_daily_skip_trace_stats.delay(yesterday_str)
        DailySMSHistory.gather_for_day(yesterday)

        # Refresh company data in freshsuccess.
        subscription_companies = Company.objects.all()
        for company in subscription_companies:
            modify_freshsuccess_account.delay(company.id)

            for profile in company.profiles.filter(user__is_active=True):
                modify_freshsuccess_user.delay(profile.user.id)
