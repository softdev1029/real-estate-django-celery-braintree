from datetime import datetime, time, timedelta
from decimal import Decimal
import random
import re
import uuid

import braintree
from braintree.exceptions import NotFoundError, ServerError
from dateutil import relativedelta
import pytz

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db.models import Case, Count, F, Q, Sum, When
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone as django_tz
from django.utils.dateparse import parse_datetime
from django.utils.functional import cached_property

from billing.exceptions import SubscriptionException
from billing.models import product
from billing.utils import (
    calculate_annual_price,
    get_twilio_discount_id,
    get_upload_limit_by_plan_id,
    map_braintree_status,
)
from companies.managers import CompanyManager
from core import models
from phone.choices import Provider
from services.freshsuccess import FreshsuccessClient
from sherpa.utils import convert_epoch
from skiptrace import SKIP_TRACE_DEFAULT_PRICE
from sms.clients import get_client

__all__ = (
    'Company',
    'company_post_save',
)


class Company(models.Model):
    """
    Companies are the core accounts for user groups on lead sherpa.
    """
    class SubscriptionStatus:
        # TODO (aww20191126) The two deprecated statues have been removed in the data. Need to
        # monitor a bit of time and if no deprecated statues come up we can remove them and set the
        # choice field on `subscription_status`. There are also 1542 records with None, which should
        # be moved to blank string instead and update logic.
        ACTIVE = 'active'
        CANCELED = 'canceled'
        PAST_DUE = 'past_due'
        PAUSED = 'paused'
        EXPIRED = 'expired'

        CHOICES = (
            (ACTIVE, 'Active'),
            (CANCELED, 'Canceled'),
            (PAST_DUE, 'Past Due'),
            (PAUSED, 'Paused'),
            (EXPIRED, 'Expired'),
        )

    class BlockReason:
        SUBSCRIPTION = 'subscription'
        TIME = 'time'
        ACTIVE_NUMBERS = 'active-numbers'
        INVALID_OUTGOING = 'invalid-outgoing'

    class RealEstateExperience:
        NOVICE = 1
        BEGINNER = 2
        INTERMEDIATE = 3
        ADVANCED = 4
        EXPERT = 5

        CHOICES = (
            (NOVICE, 'Novice - no deals yet'),
            (BEGINNER, 'Beginner'),
            (INTERMEDIATE, 'Intermediate - new but doing deals regularly'),
            (ADVANCED, 'Advanced'),
            (EXPERT, 'Expert'),
        )

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    created = models.DateTimeField(auto_now_add=True)
    invitation_code = models.ForeignKey(
        'InvitationCode', null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=64)
    default_alternate_message = models.CharField(max_length=320, null=True, blank=True)
    start_time = models.TimeField(
        default=time(9),
        help_text='Business starting time.',
    )
    end_time = models.TimeField(
        default=time(18),
        help_text='Business ending time.',
    )
    timezone = models.CharField(
        max_length=64,
        choices=list(zip(pytz.common_timezones, pytz.common_timezones)),
        default='US/Mountain',
    )
    monthly_upload_limit = models.IntegerField(default=25000)
    monthly_upload_count = models.IntegerField(default=0)
    cost_per_upload = models.DecimalField(default=.05, max_digits=2, decimal_places=2)
    sherpa_balance = models.IntegerField(default=0)
    admin_name = models.CharField(max_length=64, null=True, blank=True)
    use_sender_name = models.BooleanField(
        default=True,
        help_text='Indicate to use sender name when using carrier-approved SMS templates',
    )
    total_intial_sms_sent_today_count = models.PositiveSmallIntegerField(default=0)
    real_estate_experience_rating = models.IntegerField(default=0)
    how_did_you_hear = models.CharField(max_length=255, null=True, blank=True)

    # Company billing address info
    billing_address = models.TextField(blank=True)
    city = models.CharField(max_length=64, blank=True)
    state = models.CharField(max_length=32, blank=True)
    zip_code = models.CharField(max_length=16, blank=True)
    call_forwarding_number = models.CharField(max_length=16, null=True, blank=True)

    # Demo accounts have some limitations set to them.
    is_demo = models.BooleanField(default=False)

    # Subscription fields
    is_billing_exempt = models.BooleanField(default=False)
    braintree_id = models.CharField(max_length=10, null=True, blank=True)
    subscription_id = models.CharField(max_length=6, null=True, blank=True)
    subscription_signup_date = models.DateTimeField(auto_now_add=True)
    subscription_status = models.CharField(
        max_length=16, null=True, blank=True, choices=SubscriptionStatus.CHOICES)

    #  During the cancellation flow, a user may request a ONE-TIME discount off subscription rate.
    cancellation_discount = models.BooleanField(
        default=False,
        help_text="Determines if the next billing cycle should apply a cancellation discount",
    )
    cancellation_discount_dt = models.DateTimeField(
        null=True, blank=True, help_text="The date and time when the discount was used.")

    # Settings. These fields might be moved to a different model if they keep growing.
    threshold_exempt = models.BooleanField(
        default=False, help_text="Allow users to send bulk messages bypassing the day check rule.")
    auto_dead_enabled = models.BooleanField(default=None, null=True)
    auto_verify_prospects = models.BooleanField(
        default=False,
        help_text='When enabled, will auto-verify prospects during campaign import process.',
    )
    block_unknown_calls = models.BooleanField(
        default=True, help_text="Only allow calls from known prospects to be forwarded.")
    send_carrier_approved_templates = models.BooleanField(
        default=False,
        help_text='Allow campaigns to use carrier-approved SMS templates',
    )
    default_zapier_webhook = models.ForeignKey(
        'sherpa.ZapierWebhook',
        related_name='default_zapier_webhook',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text='Companies default Zapier webhook implementation.',
    )
    record_calls = models.BooleanField(
        default=False,
        help_text="Determines if calls should be recorded.",
    )

    # Carrier Approve template fields.
    carrier_templates = models.ManyToManyField(
        'sms.CarrierApprovedTemplate',
        related_name='carrier_template',
        help_text='Current subscribed list of CarrierApprovedTemplates.',
    )
    outgoing_company_names = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
        help_text='Comma seperated list of company names to use in Carrier-approved SMS templates.',
    )
    outgoing_user_names = ArrayField(
        models.CharField(max_length=16),
        default=list,
        blank=True,
        help_text='Comma seperated list of first names to use in Carrier-approved SMS templates.',
    )

    # TODO: (aww202020228) All fields below here could be removed.
    messaging_provider = models.CharField(
        max_length=16, default=Provider.TELNYX, choices=Provider.CHOICES)

    # TODO: (aww20190822) These cancellation fields need to be removed and instead refer to the
    # related `SubscriptionCancellationRequest` instance.
    has_cancellation_request = models.BooleanField(default=False)
    cancellation_date = models.DateField(null=True, blank=True)

    # All companies are now on a 5-day rule
    threshold_days = models.PositiveSmallIntegerField(
        default=5,
        help_text="Day amount that the company can't resend bulk messages to prospects for.",
    )

    # Allows for companies to have discounts on skip trace pricing.
    skip_trace_price = models.DecimalField(
        default=SKIP_TRACE_DEFAULT_PRICE,
        decimal_places=2,
        max_digits=3,
    )
    auto_filter_messages = models.BooleanField(
        default=True,
        help_text='Removes STOP messages from unread by default.',
    )
    enable_twilio_integration = models.BooleanField(default=False)
    allow_telnyx_add_on = models.BooleanField(default=False)
    enable_optional_opt_out = models.BooleanField(
        default=True,
        help_text="Used to toggle opt-out language for telephony providers where this is optional.",
    )
    enable_dm_golden_address = models.BooleanField(default=True)
    postcard_price = models.DecimalField(blank=True, default='0.48', max_digits=8, decimal_places=2)

    objects = CompanyManager()

    def __str__(self):
        return self.name

    class Meta:
        app_label = 'sherpa'
        verbose_name_plural = 'companies'

    def save(self, *args, **kwargs):
        """
        Special functionality for when a company is saved.
        """
        # If receiving a "Past Due" or "Active" status from braintree, we need to translate it to
        # the value expected by sherpa.
        if self.subscription_status == 'Past Due':
            self.subscription_status = self.SubscriptionStatus.PAST_DUE
        elif self.subscription_status == 'Active':
            self.subscription_status = self.SubscriptionStatus.ACTIVE

        if self.id and self.subscription_status == self.SubscriptionStatus.CANCELED:
            # When cancelling an account we need to set the churn date in freshsuccess.
            current = Company.objects.get(id=self.id)
            if current.subscription_status != self.subscription_status:
                fresh_client = FreshsuccessClient()
                payload = {
                    'is_churned': True,
                    'state': 'churned',
                }
                fresh_client.update('accounts', self.id, payload)
        elif self.id and self.subscription_status == self.SubscriptionStatus.ACTIVE:
            # When reactivating an account, we need to tell freshsuccess
            current = Company.objects.get(id=self.id)
            if current.subscription_status != self.subscription_status:
                fresh_client = FreshsuccessClient()
                payload = {
                    'is_churned': False,
                    'state': 'active',
                }
                fresh_client.update('accounts', self.id, payload)

        super(Company, self).save(*args, **kwargs)

    @property
    def has_company_specified_telephony_integration(self):
        """
        Indicate if company specificed telephony integration is setup.
        Right now this is Twilio only.
        """
        return self.telephonyconnection_set.count() > 0

    @property
    def telephony_connections(self):
        return self.telephonyconnection_set.all().values('id', 'provider')

    @property
    def has_annual_subscription(self):
        """
        Determines if the company has an annual subscription, based on if they have the annual
        discount object.
        """
        if not self.subscription:
            return False

        discounts = self.subscription.discounts
        discount_ids = ['annual-core', 'annual-pro']
        for discount in discounts:
            if discount.id in discount_ids:
                return True

        return False

    @property
    def has_valid_outgoing(self):
        """
        Return a boolean if the company has valid choices for outgoing company and names for carrier
        approved templates.
        """
        return self.outgoing_company_names and (self.outgoing_user_names or self.use_sender_name)

    @property
    def days_since_last_batch_started(self):
        from sherpa.models import StatsBatch
        latest = StatsBatch.objects.filter(campaign__market__company=self).first()

        if not latest:
            return

        today = datetime.today().date()
        delta = today - latest.created_utc.date()
        return delta.days

    @property
    def days_until_subscription_renewal(self):
        subscription = self.subscription
        if not subscription:
            return
        next_billing_date = subscription.next_billing_date
        today = datetime.today().date()
        delta = next_billing_date - today
        return delta.days

    @property
    def next_billing_date(self):
        subscription = self.subscription
        if not subscription:
            return
        return self.subscription.next_billing_date

    @property
    def days_since_last_qualified_lead(self):
        from sherpa.models import Activity
        last_added = Activity.objects.filter(
            prospect__company=self,
            title=Activity.Title.ADDED_QUALIFIED,
        ).first()

        if not last_added:
            return

        today = datetime.today().date()
        delta = today - last_added.date_utc.date()
        return delta.days

    @property
    def prospect_upload_percent(self):
        """
        Return percentage integer of the current uploads the company has used.
        """
        if self.monthly_upload_limit == 0:
            return None

        remaining = self.upload_count_remaining_current_billing_month or 0
        return round((self.monthly_upload_limit - remaining) / self.monthly_upload_limit * 100)

    @property
    def skip_payment_page(self):
        """
        Allow certain companies to skip the payment page and use free of charge.
        """
        exempt_companies = ['Cedar Crest Properties', 'National Cash Offer']
        return self.name in exempt_companies

    @property
    def created_timestamp(self):
        """
        Return the ms timestamp for when the company joined.
        """
        return convert_epoch(self.created)

    @property
    def total_initial_send_sms_daily_limit(self):
        """
        Total amount of initial bulk sends a company can make per day.
        """
        from sherpa.models import PhoneNumber
        markets = self.market_set.filter(is_active=True)
        phone_number_counts = PhoneNumber.objects.filter(
            Q(provider=Provider.TELNYX) | Q(provider=Provider.TWILIO),
            market__in=markets,
            status=PhoneNumber.Status.ACTIVE,
        ).values(
            'provider',
        ).order_by(
            'provider',
        ).annotate(c=Count(F('id')))

        telnyx = 0
        twilio = 0
        for count in phone_number_counts:
            if count['provider'] == Provider.TWILIO:
                twilio += count['c']
            else:
                telnyx += count['c']

        telnyx_limit = telnyx * settings.MESSAGES_PER_PHONE_PER_DAY
        twilio_limit = twilio * settings.MESSAGES_PER_PHONE_PER_DAY_TWILIO
        return telnyx_limit + twilio_limit

    @property
    def total_initial_messages_sent_today(self):
        """
        Returns an integer of how many initial campaign messages the company has sent today.
        """
        total_count = 0
        for market in self.market_set.all():
            total_count += market.total_intial_sms_sent_today_count
        return total_count

    @property
    def admin_profile(self):
        """
        Get the admin profile, based on the user's name...
        """
        primary = self.profiles.filter(is_primary=True).first()
        if primary:
            return primary

        # TODO: Once we switch fully to `is_primary`, this legacy logic can be removed.
        for profile in self.profiles:
            user = profile.user
            if user.get_full_name() == self.admin_name:
                return profile

    @property
    def is_cedar_crest(self):
        # Cedar Crest needs to be excluded from certain things.
        return self.name == 'Cedar Crest Properties'

    @property
    def can_push_to_campaign(self):
        return self.is_billing_exempt or self.subscription_status == self.SubscriptionStatus.ACTIVE

    @property
    def messaging_client(self):
        """
        Return the authenticated default client for the company.
        Currently the only Company level client is Telnyx.
        """
        if self.messaging_provider != Provider.TELNYX:
            raise Exception(
                f'Received invalid provider `{self.messaging_provider}` for {self.name}.')

        return get_client()

    @property
    def current_local_datetime(self):
        tz = self.timezone
        local_tz = pytz.timezone(tz)

        now = django_tz.now()

        local_dt = now.replace(tzinfo=pytz.utc).astimezone(local_tz)
        year_string = local_dt.year
        month_string = local_dt.month
        day_string = local_dt.day
        military_time_hours = local_dt.hour
        time_minutes_formatted = local_dt.minute
        datetime_now_local = datetime.strptime("%s-%s-%s %s:%s:00" % (
            year_string,
            month_string,
            day_string,
            military_time_hours,
            time_minutes_formatted,
        ), "%Y-%m-%d %H:%M:%S")

        return datetime_now_local

    @property
    def is_messaging_disabled(self):
        """
        Determines if the bulk send should be blocked for the company.

        Messaging is disabled from 8:30pm - 8:30am local time in compliance with TCPA law.
        """
        if settings.TEST_MODE:
            return False

        current_local_datetime = self.current_local_datetime
        current_hour = current_local_datetime.hour
        current_minute = current_local_datetime.minute

        within_window = False
        if current_hour == 20 and current_minute > 29:
            within_window = True
        elif current_hour >= 21:
            within_window = True
        elif current_hour < 8:
            within_window = True
        elif current_hour == 8 and current_minute < 30:
            within_window = True

        return within_window

    @property
    def total_skip_trace_savings(self):
        """
        Company's total savings from skip trace uploads.
        """
        total_existing_matches = self.uploadskiptrace_set.aggregate(Sum('total_existing_matches'))
        existing_matches_count = total_existing_matches.get('total_existing_matches__sum')

        if not existing_matches_count:
            return 0

        return existing_matches_count * self.skip_trace_price

    @property
    def upload_count_remaining_current_billing_month(self):
        """
        Each company can upload a certain amount of prospects per billing period depending on their
        plan, this method returns how many uploads they have left in this billing period.
        """
        # Old calculation that we might still need on occasion.
        # campaign_prospect_count = CampaignProspect.objects.filter(
        #     company=self,
        #     created_date__date__gte=subscription.billing_period_start_date,
        #     created_date__date__lte=subscription.billing_period_end_date,
        #     include_in_upload_count=True,
        # ).count()

        total_uploads_remaining = self.monthly_upload_limit - self.monthly_upload_count
        return total_uploads_remaining if total_uploads_remaining > 0 else 0

    @property
    def days_until_subscription(self):
        subscription = self.subscription
        if not subscription:
            return None

        delta = subscription.billing_period_end_date - django_tz.now().date() + timedelta(days=1)
        return delta.days

    @property
    def has_cancellation_request_pending(self):
        from sherpa.models import SubscriptionCancellationRequest
        return self.cancellation_requests.filter(
            status__in=[
                SubscriptionCancellationRequest.Status.PENDING,
                SubscriptionCancellationRequest.Status.ACCEPTED_PENDING,
            ],
        ).exists()

    @property
    def last_cancellation(self):
        """
        Returns the most recent cancellation object for the company.
        """
        return self.cancellation_requests.last()

    @property
    def is_cancellable(self):
        """
        Returns true if the company subscription first billing date and today is at least 3 months
        apart.
        """
        if not self.subscription or settings.TEST_MODE:
            return False

        start_billing_date = self.subscription.first_billing_date
        now = django_tz.now().date()

        if not start_billing_date:
            return False

        delta = relativedelta.relativedelta(now, start_billing_date)

        #  Add one as the initial billing date isn't being counted.
        return (delta.years * 12 + delta.months) + 1 >= 3

    @cached_property
    def braintree_transactions(self):
        """
        Return a list of the company's braintree transactions.
        """
        from billing.models import Gateway
        import braintree

        if not self.braintree_id:
            return None

        transactions = Gateway.transaction.search(
            braintree.TransactionSearch.customer_id == self.braintree_id)

        transaction_list = []
        for transaction_obj in transactions:
            if isinstance(transaction_obj.custom_fields, dict):
                transaction_type = transaction_obj.custom_fields.get('type')
            else:
                transaction_type = ''
            transaction_list.append({
                "id": transaction_obj.id,
                "datetime": transaction_obj.created_at,
                "last_4": transaction_obj.credit_card_details.last_4,
                "type": transaction_type,
                "status": map_braintree_status(transaction_obj.status),
                "amount": transaction_obj.amount,
            })

            # API is kind of weird, we just want the first page, which are the first 50 results.
            if len(transaction_list) >= 50:
                break

        return transaction_list

    @cached_property
    def subscription(self):
        """
        Return the company's braintree subscription object.
        """
        from billing.models import Gateway

        if not self.subscription_id:
            return None

        if settings.TEST_MODE and not settings.BRAINTREE_TESTING_ENABLED:
            return None

        try:
            subscription = Gateway.subscription.find(self.subscription_id)
            return subscription
        except (NotFoundError, ServerError):
            return None

    @property
    def subscription_start_date(self):
        """
        Returns the date that the company started their current braintree subscription.
        """
        if not self.subscription:
            return None

        return self.subscription.created_at.date()

    @cached_property
    def plan(self):
        from billing.models import Gateway

        if settings.TEST_MODE:
            return {'id': product.SMS_PRO, 'price': 1000, 'name': 'Pro'}

        if not self.subscription:
            return None

        plan_id = self.subscription.plan_id
        plans = Gateway.plan.all()
        plan_details = next(iter([plan for plan in plans if plan.id == plan_id]), None)

        if not plan_details:
            return None

        return {
            'id': plan_details.id,
            'price': plan_details.price,
            'name': plan_details.name,
        }

    @cached_property
    def customer(self):
        from billing.models import Gateway

        if not self.braintree_id:
            return None

        try:
            return Gateway.customer.find(self.braintree_id)
        except (NotFoundError, ServerError):
            return None

    @property
    def call_forwarding_number_display(self):
        phone_raw = self.call_forwarding_number

        if isinstance(phone_raw, float):
            # Can't always see float decimal from excel so this strip  the ".0" at end
            phone_raw = str(phone_raw)[:10]
        else:
            # STANDARDIZE PHONE NUMBER
            phone_raw = re.sub(r'\D', "", str(phone_raw))

        # remove "1" from beginning of phone number if added
        if str(phone_raw)[:1] == "1":
            phone_raw = str(phone_raw)[-10:]

        # If not 10 digit number record it as "not available"
        if len(phone_raw) != 10:
            phone = ""
        else:
            phone = phone_raw

        if len(phone) == 10:
            return "(%s) %s-%s" % (phone[:3], phone[3:6], phone[6:])
        else:
            return ""

    @property
    def profiles(self):
        """
        Return a queryset with all the profiles of the company that are not sherpa staff users.

        The reason we filter out sherpa staff users is so that they are not shown when the actual
        company users are viewing their data.
        """
        if self.id == 1:
            # Return all users for Cedar/George
            return self.userprofile_set.all()

        return self.userprofile_set.filter(user__is_staff=False)

    @property
    def expected_market_addon_count(self):
        """
        Return the amount of market addons the company should have, determined by active market
        count.
        """
        active_market_count = self.market_set.filter(is_active=True).count()

        return 0 if active_market_count == 0 else active_market_count - 1

    @property
    def expected_phone_number_addon_count(self):
        """
        Return the amount of market adds the company should have, determined by active market count.
        """
        from sherpa.models import PhoneNumber
        sub = self.subscription
        if not sub:
            return 0

        market_qs = self.market_set.all()
        expected_count = 0
        for m in market_qs:
            maintained_status_list = [PhoneNumber.Status.ACTIVE, PhoneNumber.Status.INACTIVE]
            pn_count = m.phone_numbers.filter(status__in=maintained_status_list).count()
            included_count = settings.NEW_MARKET_NUMBER_COUNT.DEFAULT
            if pn_count > included_count:
                overage_count = pn_count - included_count
                expected_count += overage_count

        # Pro plans receive and additional 10 phone numbers in their first market.
        if sub.price >= 1000:
            expected_count -= 10

        return expected_count if expected_count > 0 else 0

    @property
    def current_phone_number_count(self):
        """
        Returns the amount of active, inactive, and pending phone numbers currently allocated to
        the company via the markets tied to the company.
        """
        from sherpa.models import PhoneNumber
        return PhoneNumber.objects.filter(market__company=self).exclude(
            status=PhoneNumber.Status.RELEASED).count()

    @property
    def total_direct_mail_count(self):
        """
        Get the total number of direct mail campaign for the given company
        """
        return self.campaign_set.filter(is_direct_mail=True).count()

    @property
    def pause_price(self):
        """
        Determines the total amount a paused account will need to pay.  Default minimum is set to
        $30.
        """
        return max([30, self.current_phone_number_count])

    @property
    def current_phone_number_addon_count(self):
        """
        Returns the amount of ADDITIONAL_PHONE addons the company currently has in Braintree.
        """
        if not self.subscription or settings.TEST_MODE:
            return 0

        current_add_ons = self.subscription.add_ons
        if not len(current_add_ons):
            return 0

        return sum([
            add_on.quantity
            for add_on in current_add_ons
            if add_on.id == product.ADDITIONAL_PHONE
        ])

    @property
    def subscription_total_price(self):
        if not self.subscription or settings.TEST_MODE:
            return 0

        return self.subscription.next_billing_period_amount

    @property
    def random_outgoing_company_name(self):
        if len(self.outgoing_company_names) == 0:
            return ''

        return random.choice(self.outgoing_company_names)

    @property
    def random_outgoing_user_name(self):
        if len(self.outgoing_user_names) == 0:
            return ''

        return random.choice(self.outgoing_user_names)

    def awaiting_subscription_pause(self, cancellation_request=None):
        from sherpa.models import SubscriptionCancellationRequest
        check = self.cancellation_requests.filter(
            pause=True,
            status__in=[
                SubscriptionCancellationRequest.Status.PENDING,
                SubscriptionCancellationRequest.Status.ACCEPTED_PENDING,
            ],
        )
        if cancellation_request:
            check = check.exclude(pk=cancellation_request.pk)

        return check.exists()

    @property
    def dnc_list_count(self):
        return self.internaldnc_set.count(), self.prospect_set.filter(do_not_call=True).count()

    @property
    def latest_dm_create_date(self):
        """
         Get the latest processed direct email campaign object
        """
        dm = self.campaign_set.filter(is_direct_mail=True)
        if not dm.exists():
            return None
        return dm.first().created_date

    def campaign_meta_stats(self, start_date, end_date):
        """
        Generate campaign meta stats for a date range.
        """
        from sherpa.models import Campaign

        # Get the queryset of the daily stats instances that we'll be using.
        active_campaigns = self.campaign_set.filter(is_archived=False).prefetch_related(
            'campaigndailystats_set',
        ).filter(
            campaigndailystats__date__gte=start_date,
            campaigndailystats__date__lte=end_date,
        ).values('id').annotate(
            sent=Coalesce(Sum(F('campaigndailystats__sent')), 0),
            auto_dead=Coalesce(Sum(F('campaigndailystats__auto_dead')), 0),
            new_leads=Coalesce(Sum(F('campaigndailystats__new_leads')), 0),
            skipped=Coalesce(Sum(F('campaigndailystats__skipped')), 0),
            delivered=Coalesce(Sum(F('campaigndailystats__delivered')), 0),
            responses=Coalesce(Sum(F('campaigndailystats__responses')), 0),
            response_rate=Case(
                When(delivered=0, then=0),
                default=F('responses') / (1.0 * F('delivered')) * 100,
            ),
            delivery_rate=Case(
                When(sent=0, then=0),
                default=F('delivered') / (1.0 * F('sent')) * 100,
            ),
            performance_rating=Case(
                When(sent=0, then=0),
                default=F('new_leads') / (1.0 * F('sent')) * 100,
            ),
        )

        return [
            {
                'campaign': Campaign.objects.get(id=c['id']),
                'sent': c['sent'],
                'auto_dead': c['auto_dead'],
                'new_leads': c['new_leads'],
                'skipped': c['skipped'],
                'delivered': c['delivered'],
                'responses': c['responses'],
                'response_rate': c['response_rate'],
                'delivery_rate': c['delivery_rate'],
                'performance_rating': c['performance_rating'],
            } for c in active_campaigns
        ]

    def add_twilio_discount(self):
        """
        Adds the twilio discount to the subscription and updates the monthly upload limit.
        """
        from sherpa.models import UpdateMonthlyUploadLimit
        if not self.subscription or self.subscription_status != Company.SubscriptionStatus.ACTIVE:
            return

        twilio_discount_id = get_twilio_discount_id(self.subscription.plan_id)

        # Check if twilio discount already applied.
        if any([discount.id == twilio_discount_id for discount in self.subscription.discounts]):
            return

        # Add discount to subscription.
        self.subscription.update(
            self.subscription_id,
            {
                "discounts": {
                    "add": [{"inherited_from_id": twilio_discount_id, "never_expires": True}],
                },
            },
        )

        # Update monthly upload limit
        new_upload_limit = get_upload_limit_by_plan_id(self.subscription.plan_id, True)
        UpdateMonthlyUploadLimit.objects.create(
            company=self,
            new_monthly_upload_limit=new_upload_limit,
            update_date=self.next_billing_date or django_tz.now(),
        )

    def clear_dnc_list(self, user):
        """
        Clears DNC list and returns count of number deleted from InternalDNC and number of Prospects
        with do_not_call set to False.
        """
        removed, _ = self.internaldnc_set.all().delete()
        updated = 0
        prospects = self.prospect_set.filter(do_not_call=True)
        for prospect in prospects:
            prospect.toggle_do_not_call(user, False)
            updated += 1

        return removed, updated

    def update_usage_count(self):
        """
        Sets the company's current upload usage count based on how many campaign prospects have been
        created in the timeframe.
        """
        from sherpa.models import CampaignProspect
        subscription = self.subscription

        if not subscription:
            return

        start_billing_date = subscription.billing_period_start_date
        start_billing_datetime = parse_datetime("%s-%s-%sT08:00:00+00:00" % (
            start_billing_date.year, start_billing_date.month, start_billing_date.day),
        )

        end_billing_date = subscription.billing_period_end_date
        end_billing_datetime = parse_datetime("%s-%s-%sT23:59:00+00:00" % (
            end_billing_date.year, end_billing_date.month, end_billing_date.day),
        )

        # Will replace this with 'self.monthly_upload_count' once counts are migrated.
        campaign_prospect_count = CampaignProspect.objects.filter(
            prospect__company=self,
            created_date__gte=start_billing_datetime,
            created_date__lte=end_billing_datetime,
            include_in_upload_count=True,
        ).count()

        self.monthly_upload_count = campaign_prospect_count
        self.save(update_fields=['monthly_upload_count'])

    def clear_braintree_addresses(self):
        """
        Remove the addresses from the company's braintree account.

        This generally should not be used except for in testing against the sandbox. What happens is
        that the test accounts get filled up with addresses and braintree has a limit of 50.
        """
        from billing.models import Gateway

        if settings.BRAINTREE_ENV != braintree.Environment.Sandbox:
            return

        addresses = self.customer.addresses
        for address in addresses:
            Gateway.address.delete(self.customer.id, address.id)

    def check_subscription_retry(self):
        """
        Check if the subscription is past due and has a balance due. If so, retry the payment.

        :return Company: Returns the company object with its updated subscription status.
        """
        if self.subscription_status != Company.SubscriptionStatus.PAST_DUE:
            return self

        if Decimal(self.subscription.balance) > 0:
            payment_success = self.retry_subscription_payment()
            if payment_success:
                # We could wait for the webhook to come, but frontend will need to
                # update the company's subscription status right away so they can use
                # the system.
                self.subscription_status = Company.SubscriptionStatus.ACTIVE
                self.save(update_fields=['subscription_status'])
        else:
            # Company does not have any balance due on their subscription.
            self.subscription_status = Company.SubscriptionStatus.ACTIVE
            self.save(update_fields=['subscription_status'])

        return self

    def retry_subscription_payment(self):
        """
        When a company has a past due payment, we need to retry the payment to get them back on
        their active subscription status.

        :return: boolean of successful payment
        """
        from billing.models import Gateway

        subscription = self.subscription
        retry_result = Gateway.subscription.retry_charge(
            self.subscription_id,
            subscription.balance,
        )
        if retry_result.is_success:
            submit_for_settlement_result = Gateway.transaction.submit_for_settlement(
                retry_result.transaction.id,
            )
            return submit_for_settlement_result.is_success

        return False

    def create_subscription(self, plan_id, is_annual):  # noqa: C901
        """
        Creates a new subscription for a company.

        :param plan_id: The subscription plan id from braintree.
        :param is_annual: Boolean to determine if the subscription should be annual.
        :return: Response object from braintree subscription creation.
        """
        from billing.models import Gateway, Transaction

        try:
            # Need to clear the cached customer because usually they will have added it in the
            # request cycle.
            del self.customer
        except AttributeError:
            pass

        customer = self.customer
        if not customer:
            raise SubscriptionException('Must have a customer to create a subscription.')

        create_payload = {
            'payment_method_token': customer.payment_methods[0].token,
            'plan_id': plan_id,
        }

        if is_annual:
            # Special handling for users that signup for an annual subscription.
            amount = calculate_annual_price(plan_id)

            annual_transaction = Transaction.authorize(self, 'Annual Subscription', amount)
            if not annual_transaction.is_authorized:
                raise SubscriptionException('Error authorizing payment.')
            annual_transaction.charge()

            annual_discount_id = f'annual-{plan_id}'
            create_payload['discounts'] = {'add': [{'inherited_from_id': annual_discount_id}]}
        elif (
            plan_id != product.SMS_STARTER and
            self.invitation_code and
            self.invitation_code.discount_code
        ):
            # Apply the discount code as long as not signing up for starter plan.
            create_payload['discounts'] = {'add': [
                {'inherited_from_id': self.invitation_code.discount_code},
            ]}

        if 'discounts' not in create_payload:
            create_payload['discounts'] = {'add': []}

        # Add twilio discount
        create_payload['discounts']['add'].append({
            'inherited_from_id': get_twilio_discount_id(plan_id),
            'never_expires': True,
        })

        response = Gateway.subscription.create(create_payload)

        if response.is_success:
            # When the subscription is successful, there are fields that need to be updated.
            subscription_data = response.subscription
            monthly_upload_limit = get_upload_limit_by_plan_id(plan_id, with_twilio=True)

            self.subscription_id = subscription_data.id
            self.subscription_status = subscription_data.status
            self.subscription_signup_date = django_tz.now()
            self.monthly_upload_limit = monthly_upload_limit
            self.save(update_fields=[
                'subscription_id',
                'subscription_status',
                'subscription_signup_date',
                'monthly_upload_limit',
            ])

        return response

    def create_property_tags(self):
        """
        Every company should have a set of default system prospect tags.
        """
        from properties.models import PropertyTag

        tags = [
            {'name': 'Absentee', 'distress_indicator': True},
            {'name': 'Bankruptcy', 'distress_indicator': True},
            {'name': 'Divorce', 'distress_indicator': True},
            {'name': 'Expired Listing', 'distress_indicator': True},
            {'name': 'Golden Address', 'distress_indicator': False},
            {'name': 'Judgement', 'distress_indicator': True},
            {'name': 'Lien', 'distress_indicator': True},
            {'name': 'Pre-foreclosure', 'distress_indicator': True},
            {'name': 'Probate / Death', 'distress_indicator': True},
            {'name': 'Vacant', 'distress_indicator': True},
            {'name': 'Tax default', 'distress_indicator': True},
            {'name': 'Quitclaim', 'distress_indicator': True},
            {'name': 'High Equity', 'distress_indicator': False},
        ]

        for tag in tags:
            PropertyTag.objects.get_or_create(company=self, **tag)

    def user_profile_stats(self, start_date, end_date):
        """
        Return a list of agents with their time-filtered sending stats.

        :return list[dict]: Data about the time-filtered stats for an agent.
        """
        queryset = self.profiles.filter(user__is_active=True)
        stats = []
        for user_profile in queryset:
            data = user_profile.send_stats(start_date, end_date)
            data['id'] = user_profile.id
            data['name'] = user_profile.user.get_full_name()
            stats.append(data)
        return stats

    def cancel_subscription(self, subscription_cancellation=None):
        """
        Method to cancel a company's subscription.

        1) update their company data
        2) release their sherpa numbers
        3) set their skip trace price to normal price if they had a discount
        4) cancel their braintree subscription
        5) update their cancellation request
        6) send an email confirming the user their cancellation

        """
        from billing.models import Gateway
        from phone.tasks import deactivate_company_markets
        from sherpa.models import SubscriptionCancellationRequest

        subscription_id = self.subscription_id

        # Clear subscription_id so user still has access to skip trace.
        self.subscription_status = self.SubscriptionStatus.CANCELED
        self.subscription_id = ''
        self.has_cancellation_request = False
        self.cancellation_date = None

        # Update skip trace price from .12 to default
        self.skip_trace_price = SKIP_TRACE_DEFAULT_PRICE

        self.save(update_fields=[
            'subscription_status',
            'subscription_id',
            'has_cancellation_request',
            'cancellation_date',
            'skip_trace_price',
        ])

        # Call task and release sherpa phone numbers.
        deactivate_company_markets.delay(self.id)

        # Cancel braintree subscription.
        if subscription_id:
            Gateway.subscription.cancel(subscription_id)

        # Update cancellation request
        if subscription_cancellation:
            subscription_cancellation.status = SubscriptionCancellationRequest.Status.COMPLETE
            subscription_cancellation.save()

    def reactivate(self):
        """
        Reactivate an account that has been previously fully deactivated.
        """
        self.subscription_id = ''
        self.status = 'active'
        self.save()

    def replace_addon(self, previous_add_on, new_add_on):
        """
        Replace a braintree addon with another one.
        """
        from billing.models import Gateway

        subscription, has_add_on = self.has_addon(previous_add_on)

        if not subscription or not has_add_on:
            # Nothing to replace.
            return

        # Get the quantity of the addon that we're replacing.
        for add_on in subscription.add_ons:
            if add_on.id == previous_add_on:
                previous_quantity = add_on.quantity
                break

        # Remove the existing addon.
        Gateway.subscription.update(self.subscription_id, {
            "add_ons": {
                "remove": [previous_add_on],
            },
        })

        # Create the new add-on, or update its quantity.
        _, has_new_addon = self.has_addon(new_add_on)

        if has_new_addon:
            # Subscription has the new addon, we need to incremente the quantity.
            for add_on in subscription.add_ons:
                if add_on.id == new_add_on:
                    next_quantity = add_on.quantity
                    break

            Gateway.subscription.update(self.subscription_id, {
                "add_ons": {
                    "update": [
                        {
                            "existing_id": new_add_on,
                            "quantity": next_quantity + previous_quantity,
                        },
                    ],
                },
            })
        else:
            # Add the replacement addon.
            Gateway.subscription.update(self.subscription_id, {
                "add_ons": {
                    "add": [
                        {
                            "inherited_from_id": new_add_on,
                            "quantity": previous_quantity,
                        },
                    ],
                },
            })

    def has_addon(self, add_on_id):
        """
        Check if the company has a specific addon.

        :return: Returns a tuple of the subscription with a boolean if it has the add-on. The reason
                 for returning the subscription too instead of just a boolean is that we need to
                 fetch the subscription anyway, so we don't want to have to do that again after.
        """
        subscription = self.subscription
        if not subscription:
            return None, False

        has_add_on = False
        for add_on in subscription.add_ons:
            if add_on.id == add_on_id:
                has_add_on = True

        return subscription, has_add_on

    def modify_addon_price(self, add_on_id, price):
        """
        Update the price of an addon in a braintree subscription.

        This is used when we update the price of an addon in braintree. The price for the already
        allocated add-on does not update when doing this, so we need to run a script to update the
        add-on price for the existing addon.

        :arg add_on_id str: id of the addon to update price for.
        :arg price str: amount to update the add_on to.
        """
        from billing.models import Gateway

        subscription = self.subscription
        if not subscription:
            return

        has_existing_add_on_phone = False
        for add_on in subscription.add_ons:
            if add_on.id == add_on_id:
                has_existing_add_on_phone = True

        if not has_existing_add_on_phone:
            return

        Gateway.subscription.update(self.subscription_id, {
            "add_ons": {
                "update": [
                    {
                        "existing_id": add_on_id,
                        "amount": price,
                    },
                ],
            },
        })

    def update_subscription_plan_price(self, plan_id, new_price):
        """
        Update the price of a given plan.

        When you update a plan in braintree, it does not automatically update the price of the
        subscription. For that you need to update the subscription price separately, which is what
        we're doing here.

        https://developers.braintreepayments.com/reference/request/subscription/update/python

        :arg plan_id str: The plan id that we're wanting to update the subscription price for.
        """
        from billing.models import Gateway

        subscription = self.subscription

        if not subscription or not subscription.plan_id == plan_id:
            return

        payload = {"price": new_price}
        Gateway.subscription.update(self.subscription_id, payload)

    def update_phone_number_addons(self):
        """
        Update the quantity of phone number addons for a user's subscription.

        :arg quantity int: Amount of addons to add to the user's subscription.
        """
        from billing.models import Gateway

        subscription, has_existing_add_on_phone = self.has_addon(product.ADDITIONAL_PHONE)

        if not subscription or settings.TEST_MODE:
            return

        updated_quantity = self.expected_phone_number_addon_count
        if updated_quantity == 0 and has_existing_add_on_phone:
            # Remove the add-on if the subscription should no longer have it.
            Gateway.subscription.update(self.subscription_id, {
                "add_ons": {
                    "remove": [product.ADDITIONAL_PHONE],
                },
            })
        elif has_existing_add_on_phone:
            # Update the subscription's additional phone quantity.
            Gateway.subscription.update(self.subscription_id, {
                "add_ons": {
                    "update": [
                        {
                            "existing_id": product.ADDITIONAL_PHONE,
                            "quantity": updated_quantity,
                        },
                    ],
                },
            })
        else:
            # They don't have the addon, but they should.
            Gateway.subscription.update(self.subscription_id, {
                "add_ons": {
                    "add": [
                        {
                            "inherited_from_id": product.ADDITIONAL_PHONE,
                            "quantity": updated_quantity,
                        },
                    ],
                },
            })

    def copy_alternate_message_to_templates(self):
        """
        Copy alternate message to all templates.
        """
        from sherpa.models import SMSTemplate
        SMSTemplate.objects.filter(company=self).update(
            alternate_message=self.default_alternate_message)

    def credit_sherpa_balance(self, amount):
        """
        Add to company's credits.
        """
        from billing.models import Transaction

        if amount < settings.MIN_CREDIT:
            return f'Amount is less than minimum. Must be at least {settings.MIN_CREDIT} credits.'

        if not self.is_billing_exempt:
            authorize_amount = amount * settings.SHERPA_CREDITS_CHARGE
            transaction = \
                Transaction.authorize(self, f'Sherpa Credits - {amount}', authorize_amount)
            if not settings.TEST_MODE:
                if transaction.is_authorized:
                    transaction.charge()
                if not transaction.is_charged:
                    return transaction.failure_reason

            self.sherpa_balance += amount
        self.save(update_fields=['sherpa_balance'])

    def debit_sherpa_balance(self, amount):
        """
        Debit company's credits.
        """
        if not self.has_sherpa_balance(amount):
            return 'insufficient balance'

        if not self.is_billing_exempt:
            self.sherpa_balance -= amount
            self.save(update_fields=['sherpa_balance'])

    def has_sherpa_balance(self, amount=1):
        """
        Check to see if company has enough credits.
        """
        return self.sherpa_balance >= amount or self.is_billing_exempt

    #  Cancellation Flow methods.
    def apply_cancellation_discount_to_subscription(self):
        """
        Applies the cancellation discount to the company's subscription.
        """
        if not self.subscription_id or settings.TEST_MODE:
            return

        from billing.models import Gateway

        plan_id = self.subscription.plan_id
        discount_id = f"50off_{plan_id}"
        Gateway.subscription.update(
            self.subscription_id,
            {'discounts': {'add': [{'inherited_from_id': discount_id}]}},
        )

        if self.subscription:
            del self.subscription
        return self.subscription_total_price

    def set_pause_subscription_price(self, amount):
        """
        Updates the company's subscription to their pause price and adds an UpdateMonthlyUploadLimit
        to 0.  This is step 1 of the pause cancellation flow.  `.pause_subscription` is the final
        step which will run on the night of the the company's next billing date and set the status
        to PAUSED.

        :param amount float: The amount to set the price.
        """
        from sherpa.models import UpdateMonthlyUploadLimit
        if not self.subscription_id or settings.TEST_MODE:
            return 30

        from billing.models import Gateway
        payload = {'price': amount}

        add_ons = self.subscription.add_ons
        discounts = self.subscription.discounts

        if add_ons:
            payload['add_ons'] = {
                'update': [{'existing_id': a.id, 'amount': 0} for a in add_ons],
            }
        if discounts:
            payload['discounts'] = {
                'update': [{'existing_id': a.id, 'amount': 0} for a in discounts],
            }

        Gateway.subscription.update(self.subscription_id, payload)

        UpdateMonthlyUploadLimit.objects.create(
            company=self,
            new_monthly_upload_limit=0,
            update_date=self.next_billing_date or django_tz.now(),
        )

    def pause_subscription(self, subscription_cancellation=None):
        """
        Pauses the subscription.  This is the final step during the pause cancellation flow.  Runs
        during the nightly `process_cancellation_requests` task.  Note: This will set the pause
        price again in case the company has ordered numbers between requesting a pause and this
        method running.

        :param subscription_cancellation SubscriptionCancellationRequest: The cancellation request.
        """
        from sherpa.models import SubscriptionCancellationRequest
        self.set_pause_subscription_price(self.pause_price)
        self.subscription_status = Company.SubscriptionStatus.PAUSED
        self.save(update_fields=['subscription_status'])

        # Update cancellation request
        if subscription_cancellation:
            subscription_cancellation.status = SubscriptionCancellationRequest.Status.COMPLETE
            subscription_cancellation.save(update_fields=['status'])

    def switch_subscription(self, new_plan_id):
        """
        Updates company's braintree subscription plan and price to a new plan based on the provided
        ID.

        :param new_plan_id string: The ID of the new braintree subscription plan.
        """
        if not self.subscription_id or settings.TEST_MODE:
            return

        from billing.models import Gateway
        from sherpa.models import UpdateMonthlyUploadLimit

        plans = Gateway.plan.all()
        new_plan = next(iter([plan for plan in plans if plan.id == new_plan_id]), None)

        if not new_plan:
            return

        Gateway.subscription.update(
            self.subscription_id, {'plan_id': new_plan.id, 'price': new_plan.price})

        options = {
            product.SMS_SH2000: 50000,
            product.SMS_ENTERPRISE: 50000,
            product.SMS_PRO: 25000,
            product.SMS_CORE: 10000,
            product.SMS_STARTER: 5000,
        }

        UpdateMonthlyUploadLimit.objects.create(
            company=self,
            new_monthly_upload_limit=options[new_plan_id],
            update_date=self.next_billing_date or django_tz.now(),
        )

        if self.subscription:
            del self.subscription
        self.update_phone_number_addons()
        return self.subscription_total_price


@receiver(post_save, sender=Company)
def company_post_save(sender, instance, created, raw, *args, **kwargs):
    """
    This feature "stages" has been put on "hold" and development will commence when we have time to
    think it thorugh more

    Stages are used to enable  push to zapier button
    """
    from sherpa.models import LeadStage
    if raw or not created:
        # Don't run when loading fixtures or updating a company.
        return

    # Set the company's skip trace price to their invitation code price.
    invitation_code = instance.invitation_code
    if invitation_code:
        instance.skip_trace_price = invitation_code.skip_trace_price
        instance.save(update_fields=['skip_trace_price'])

    # Create the default lead stages.
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Initial Message Sent', sort_order=1)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Response Received', sort_order=2)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Make Offer', is_custom=True, sort_order=3)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Followup', is_custom=True, sort_order=4)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Appointment', is_custom=True, sort_order=5)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Cold', is_custom=True, sort_order=6)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Refer to Agent', is_custom=True, sort_order=7)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Dead', sort_order=8)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Pushed to Podio', sort_order=9)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Deal Closed', is_custom=True, sort_order=10)
    LeadStage.objects.get_or_create(
        company=instance, lead_stage_title='Dead (Auto)', sort_order=11)
