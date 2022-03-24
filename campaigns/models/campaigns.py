from datetime import datetime, timedelta
from decimal import Decimal
from importlib import import_module
import json
import re
import uuid

from model_utils import FieldTracker
import pytz
import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.core.exceptions import MultipleObjectsReturned, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction as django_transaction
from django.db.models import Count, F, Q, Sum
from django.template.loader import render_to_string
from django.utils import timezone as django_tz

from accounts.models.accounts import UserProfile
from accounts.models.company import Company
from billing.models.product import ADDITIONAL_MARKET
from campaigns.managers import CampaignManager
from companies.models import UploadBaseModel
from core import models
from core.mixins import SortOrderModelMixin
from core.utils import clean_phone, number_display
from markets.utils import format_telnyx_available_numbers
from phone.choices import Provider
from prospects.managers import ProspectManager
from sherpa.abstracts import AbstractNote
from sherpa.utils import sign_street_view_url
from skiptrace.models import SkipTraceProperty, UploadSkipTrace
from sms import OPT_OUT_LANGUAGE, OPT_OUT_LANGUAGE_TWILIO, TAG_MAPPINGS
from sms.clients import get_client, TelnyxClient
from sms.utils import fetch_phonenumber_info, get_tags

__all__ = (
    'Activity', 'AreaCodeState', 'Campaign', 'CampaignAccess', 'CampaignProspect', 'InternalDNC',
    'LeadStage', 'Market', 'Note', 'Prospect', 'SherpaTask', 'UploadInternalDNC', 'UploadProspects',
    'ZapierWebhook',
)

User = get_user_model()


class Market(models.Model):
    """
    Grouping between a company and a parent market.

    Each company can have a presence in separate markets and that relationship's data is stored in
    this model.
    """
    company = models.ForeignKey('Company', on_delete=models.CASCADE)

    # Only 57 old markets < id 571 that have null parent_market.
    parent_market = models.ForeignKey(
        'AreaCodeState', null=True, blank=True, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)

    # One time transactions are used to cover prorated coverage for the first month.
    one_time_transaction = models.ForeignKey(
        'billing.Transaction', null=True, blank=True, on_delete=models.CASCADE)

    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    area_code1 = models.CharField(null=True, blank=True, max_length=3)
    area_code2 = models.CharField(null=True, blank=True, max_length=3)
    call_forwarding_number = models.CharField(max_length=255, null=True, blank=True)

    # last_index_assigned is used when assigning a phone number.
    last_index_assigned = models.IntegerField(default=0)
    total_intial_sms_sent_today_count = models.IntegerField(default=0)

    # On telnyx we can group numbers into pools of a profile by market and send from the pool.
    messaging_profile_id = models.CharField(max_length=36, blank=True)
    current_spam_cooldown_period_end = models.DateTimeField(
        null=True, blank=True, help_text='Date time when spam cooldown ends.')

    # Determines how many phones come with the market. If going over this amount the user will incur
    # a subscription increase via add-on, and also if above this amount when releasing the
    # `phone_number` addon should be decremented.
    included_phones = models.PositiveSmallIntegerField(default=30)

    # TODO: (awwester20190823) Monthly amount isn't actually being used as the number to charge. The
    # amount to charge per month actually comes from subscription addons.
    monthly_amount = models.DecimalField(null=True, blank=True, max_digits=8, decimal_places=2)
    one_time_amount = models.DecimalField(null=True, blank=True, max_digits=8, decimal_places=2)

    class Meta:
        app_label = 'sherpa'
        ordering = ('id',)

    def __str__(self):
        return self.name

    @property
    def has_sufficient_numbers(self):
        """
        Each campaign requires that there are at least 20 numbers in the market due to
        deliverability constraints from the carriers (<6 messages per minute).
        """
        minimum = Provider.get_market_minimum(self.phone_provider)
        return self.bulk_phone_numbers.count() >= minimum

    @property
    def bulk_phone_numbers(self):
        """
        Returns a queryset of phone numbers that are valid to bulk send in the market's campaigns.
        """
        from sherpa.models import PhoneNumber

        return PhoneNumber.objects.filter(
            market=self,
            status=PhoneNumber.Status.ACTIVE,
            provider=self.phone_provider,
        )

    @property
    def has_pending_numbers(self):
        """
        Returns a boolean if the market has any pending phone numbers.
        """
        from sherpa.models import PhoneNumber
        return self.phone_numbers.filter(status=PhoneNumber.Status.PENDING).exists()

    @property
    def messaging_profile_name(self):
        """
        Messaging profile name is made from the company & market names.
        """
        return f'{self.company.name} - {self.name}'

    @property
    def phone_provider(self):
        """
        Phone provider key for this Market
        """
        provider = Provider.get_by_name(self.name)

        # Right now, we are only allowing Cedar Crest to use Inteliquent.
        if provider == Provider.INTELIQUENT and not self.company.is_cedar_crest:
            return Provider.DEFAULT

        return provider

    @property
    def client(self):
        """
        SMS client for this Market
        """
        return get_client(self.phone_provider, company_id=self.company_id)

    def repurchase_numbers(self):
        """
        Repurchase the phone numbers of this market.

        Sometimes the market accidentally gets deactivated and the user wants to repurchase their
        numbers that were released.
        """
        from sherpa.models import PhoneNumber

        # Will change this when we refactor to make telephony scalable.
        if self.phone_provider != Provider.TELNYX:
            return

        client = TelnyxClient()
        number_list = [f'+1{phone_number.phone}' for phone_number in self.phone_numbers.all()]
        order_response = client.create_number_order(
            number_list, messaging_profile_id=self.messaging_profile_id)

        for telnyx_phone_number in order_response.phone_numbers:
            full_phone_number = telnyx_phone_number.get('phone_number')
            phone_number = full_phone_number.replace('+1', '')
            pn_obj = self.phone_numbers.get(phone=phone_number, status=PhoneNumber.Status.RELEASED)
            pn_obj.status = PhoneNumber.Status.ACTIVE
            pn_obj.save(update_fields=['status'])

    def update_numbers(self, payload):
        """
        Update all numbers in the market with a given payload.

        - Sometimes telnyx has a bug where it does not properly assign the numbers that are
        purchased to the messaging profile.
        - Some numbers can be setup with a connection id.
        """
        from sherpa.models import PhoneNumber

        # Will change this when refactoring to make telephony scalable.
        if self.phone_provider != Provider.TELNYX:
            return

        client = TelnyxClient()
        dumped_payload = json.dumps(payload)
        for phone_number in self.phone_numbers.exclude(status=PhoneNumber.Status.RELEASED):
            client.update_messaging_number(phone_number.provider_id, dumped_payload)

    def create_addon(self, quantity=1):
        """
        Add or update the market addons for the company.

        :arg quantity int: Amount of addons to add to the user's subscription.
        :return: Returns a boolean true/false if the transaction went through ok.
        """
        from billing.models import Gateway

        company = self.company
        has_existing_add_on_market = False
        add_on_id = ADDITIONAL_MARKET
        for add_on in company.subscription.add_ons:
            if add_on.id == add_on_id:
                quantity += add_on.quantity
                has_existing_add_on_market = True

        if has_existing_add_on_market:
            Gateway.subscription.update(company.subscription_id, {
                "add_ons": {
                    "update": [
                        {
                            "existing_id": add_on_id,
                            "quantity": quantity,
                        },
                    ],
                },
            })
        else:
            Gateway.subscription.update(company.subscription_id, {
                "add_ons": {
                    "add": [
                        {
                            "inherited_from_id": add_on_id,
                            "quantity": quantity,
                        },
                    ],
                },
            })

    def purchase_numbers(self, quantity):
        """
        DEPRECATED: This might not be used anymore?
        """
        from phone.tasks import purchase_market_numbers

        purchase_market_numbers.delay(self.id, quantity)

    def purchase_number(self, phone_number):
        """
        DEPRECATED: Purchase a single number for a market.

        This should no longer be used because with telnyx we purchase from a list instead of
        individual.

        :arg phone_number: the phone number that is to be purchased.
        """
        raise NotImplementedError("Can no longer purchase individual numbers.")
        from sherpa.models import PhoneNumber

        client = self.company.messaging_client
        if self.company.messaging_provider == Provider.TELNYX:
            response = client.purchase_number(phone_number)
            payload = response.data.get('data').get('payload')
            provider_id = payload.get('id')
        else:
            raise Exception('Received invalid provider `{self.company.messaging_provider}`.')

        phone_number_clean = clean_phone(phone_number)
        PhoneNumber.objects.create(
            phone=phone_number_clean,
            company=self.company,
            market=self,
            provider=self.company.provider,
            provider_id=provider_id,
        )

    def deactivate(self):
        # TODO: (aww20190822) We also want to remove their extra market subscription if applicable
        # and adjust their phone number addon count, however need more examples before having those
        # rules final.
        self.release_numbers()
        self.is_active = False

        # TODO: Should delete the messaging profile too.
        self.save()

    def release_numbers(self):
        """
        Release all the twilio phone numbers of the market.
        """
        from phone.tasks import release_company_phone_numbers
        from sherpa.models import PhoneNumber

        phone_number_list = self.phone_numbers.exclude(status=PhoneNumber.Status.RELEASED)
        release_company_phone_numbers(phone_number_list, self.company.id)

    def charge(self):
        """
        Perform the charge for a company's one time amount charge on a market.
        """
        if not self.one_time_transaction:
            return

        trans = self.one_time_transaction
        if all([
                not trans.is_failed,
                trans.is_authorized or settings.TEST_MODE,
                not trans.is_charged,
                self.one_time_amount > 0,
        ]):
            trans.charge(self.one_time_amount)

    def get_available_numbers(self, limit=None, best_effort=False, return_numbers=False):
        """
        Return a list of available numbers for the market's area code.
        """
        # Will change this when refactoring to make telephony scalable.
        # Not doing this for Twilio as we won't be checking this but just pulling
        # whatever the user has in their credentials.
        if self.phone_provider != Provider.TELNYX:
            return []

        client = TelnyxClient()
        if limit:
            telnyx_response = client.get_available_numbers(
                self.area_code1,
                limit=limit,
                best_effort=best_effort,
            )
        else:
            telnyx_response = client.get_available_numbers(self.area_code1, best_effort=best_effort)

        return format_telnyx_available_numbers(telnyx_response, return_numbers=return_numbers)

    def add_numbers(self, add_quantity, user, best_effort):
        """
        Add a given amount of numbers to a market.

        We will add the amount passed in to the `add_quantity`, however the user will only be
        changed for the numbers that are over the market's included amount.

        :param add_quantity: Amount of phone numbers to add to the market.
        :param user: The user who is adding the numbers to the market.
        :return: returns a tuple of success (bool), message (str).
        """
        from billing.models import Transaction
        from phone.tasks import purchase_phone_numbers_task
        from sherpa.models import PhoneNumber

        if self.company.is_cedar_crest:
            # Override charging cedar crest.
            purchase_phone_numbers_task.delay(self.id, add_quantity, 0, user.id)
            return True, ""
        else:
            # Get the amount of numbers that are overrage for the market.
            current_number_count = self.phone_numbers.exclude(
                status=PhoneNumber.Status.RELEASED).count()
            updated_phone_count = current_number_count + add_quantity
            overrage_phone_count = updated_phone_count - self.included_phones
            if overrage_phone_count < 0:
                overrage_phone_count = 0

            # Authorize the transaction amount $1 per overrage number
            transaction = None
            purchase_quantity = 0
            if overrage_phone_count > 0:
                if overrage_phone_count >= add_quantity:
                    purchase_quantity = add_quantity
                else:
                    purchase_quantity = overrage_phone_count
                purchase_amount = Decimal(purchase_quantity)
                transaction = Transaction.authorize(
                    self.company,
                    'Additional Phone Numbers',
                    purchase_amount,
                )
                if not transaction.is_authorized:
                    # Something went wrong.
                    return False, 'Failure to charge for numbers.'
                else:
                    transaction.type = Transaction.Type.PHONE_PURCHASE
                    transaction.save(update_fields=['type'])

            purchase_phone_numbers_task.delay(
                self.id,
                add_quantity,
                purchase_quantity,
                user.id,
                transaction_id=transaction.id if transaction else None,
                best_effort=best_effort,
            )
        return True, ""

    @property
    def created_date_calculated(self):
        """
        Return the formatted created date in the US/Mountain timezone.
        """
        local_tz = pytz.timezone('US/Mountain')

        if self.created_date:
            local_dt = self.created_date.replace(tzinfo=pytz.utc).astimezone(local_tz)
            year_string = local_dt.year
            month_string = local_dt.month
            day_string = local_dt.day
            military_time_hours = local_dt.hour
            time_minutes_formatted = local_dt.minute
            datetime_now_local = datetime.strptime(
                "%s-%s-%s %s:%s:00" % (
                    year_string,
                    month_string,
                    day_string,
                    military_time_hours,
                    time_minutes_formatted,
                ),
                "%Y-%m-%d %H:%M:%S")

            return datetime_now_local

        return ''

    @property
    def name_with_area_code(self):
        return "%s - %s" % (self.name, self.area_code1)

    @property
    def total_phone_active(self):
        from sherpa.models import PhoneNumber
        return PhoneNumber.objects.filter(market=self, status='active').count()

    @property
    def total_phone_inactive(self):
        from sherpa.models import PhoneNumber
        return PhoneNumber.objects.filter(market=self, status='inactive').count()

    @property
    def total_initial_send_sms_daily_limit(self):
        """
        Phone numbers should not send out more than 100 numbers or they have a higher chance of
        being marked as spam.
        """
        from sherpa.models import PhoneNumber
        phone_numbers = PhoneNumber.objects.filter(market=self, status=PhoneNumber.Status.ACTIVE)
        limit_per_phone = settings.MESSAGES_PER_PHONE_PER_DAY
        if self.phone_provider == Provider.TWILIO:
            limit_per_phone = settings.MESSAGES_PER_PHONE_PER_DAY_TWILIO
        # TODO: Design something that handles differences per provider.
        # Temporarily just setting the Inteliquent limit ridiculously high to
        # conduct our test.
        if self.phone_provider == Provider.INTELIQUENT:
            return 9999999999
        return phone_numbers.count() * limit_per_phone

    @property
    def total_sends_available(self):
        """
        Companies may only send a certain amount of messages per day to a market.
        """
        if self.total_intial_sms_sent_today_count >= self.total_initial_send_sms_daily_limit:
            return 0

        return self.total_initial_send_sms_daily_limit - self.total_intial_sms_sent_today_count

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
    def call_forwarding_number_calculated(self):
        if self.call_forwarding_number is None:
            return "%s" % self.company.call_forwarding_number_display

        return "%s" % self.call_forwarding_number_display

    @property
    def active_campaigns(self):
        return self.campaign_set.filter(is_archived=False)


class Campaign(models.Model):
    """
    Company can have many Campaigns. Campaigns are never deleted but rather is_archived is set to
    True. Campaigns can be optionally organized by setting the folder field.
    """
    class Health:
        GOOD = 'good'
        CHOICES = ((GOOD, 'Good'),)

    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    market = models.ForeignKey('Market', null=True, blank=True, on_delete=models.CASCADE)
    zapier_webhook = models.ForeignKey(
        'ZapierWebhook', null=True, blank=True, on_delete=models.SET_NULL)
    issues = models.ManyToManyField('campaigns.CampaignIssue', blank=True)
    tags = models.ManyToManyField('campaigns.CampaignTag', blank=True)
    sms_template = models.ForeignKey(
        'SMSTemplate',
        null=True,
        blank=True,
        related_name='sms_template_name',
        on_delete=models.SET_NULL,
    )
    lead_stage_filter = models.ForeignKey(
        'LeadStage', null=True, blank=True, on_delete=models.SET_NULL)
    owner = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL)
    followup_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)

    name = models.CharField(max_length=255)
    created_date = models.DateTimeField(auto_now_add=True, db_index=True)
    health = models.CharField(max_length=16, default=Health.GOOD, choices=Health.CHOICES)

    # Determines the currently active campaign.
    is_default = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_direct_mail = models.BooleanField(default=False)

    # Determines if the campaign has a prospect that is marked with priority.
    has_priority = models.BooleanField(default=False)

    # This section contains aggregated stat fields
    campaign_stats = models.OneToOneField(
        'campaigns.CampaignAggregatedStats',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    total_priority = models.PositiveSmallIntegerField(default=0)
    total_prospects = models.IntegerField(default=0)
    total_sms_followups = models.IntegerField(default=0)
    total_skipped = models.IntegerField(default=0)
    total_dnc_count = models.IntegerField(default=0)
    total_sms_sent_count = models.IntegerField(default=0)
    total_sms_received_count = models.IntegerField(default=0)
    total_wrong_number_count = models.IntegerField(default=0)
    total_auto_dead_count = models.IntegerField(default=0)
    total_initial_sent_skipped = models.IntegerField(default=0)
    total_mobile = models.IntegerField(default=0)
    total_landline = models.IntegerField(default=0)
    total_phone_other = models.IntegerField(default=0)
    total_intial_sms_sent_today_count = models.IntegerField(default=0)
    total_leads = models.IntegerField(default=0)
    has_delivered_sms_only_count = models.IntegerField(default=0)

    has_unread_sms = models.BooleanField(default=False)
    show_unviewed_only_filter = models.BooleanField(default=False)
    show_qualified_lead_filter = models.BooleanField(default=False)
    # Deprecated - use auto_dead_enabled in `Company` instead
    set_auto_dead = models.BooleanField(default=True)
    set_auto_dead_select = models.CharField(
        max_length=255, default='Yes', choices=[('No', 'No'), ('Yes', 'Yes')])
    podio_push_email_address = models.CharField(null=True, blank=True, max_length=255)
    skip_trace_cost_per_record = models.CharField(max_length=255, default='.07', choices=[
        ('.04', '.04'), ('.05', '.05'), ('.06', '.06'), ('.07', '.07'), ('.08', '.08'),
        ('.09', '.09'), ('.10', '.10'), ('.11', '.11'), ('.12', '.12'), ('.13', '.13'),
        ('.14', '.14'), ('.15', '.15'), ('.16', '.16'), ('.17', '.17'), ('.18', '.18'),
        ('.19', '.19'), ('.20', '.20'), ('.21', '.21'), ('.22', '.22'), ('.23', '.23'),
        ('.24', '.24'), ('.25', '.25'), ('.26', '.26'), ('.27', '.27'), ('.28', '.28'),
        ('.29', '.29'), ('.30', '.30'), ('.31', '.31'), ('.32', '.32'), ('.33', '.33'),
        ('.34', '.34'), ('.35', '.35'),
    ])

    call_forward_number = models.CharField(null=True, blank=True, max_length=255)
    timezone = models.CharField(
        max_length=255,
        choices=list(zip(pytz.common_timezones, pytz.common_timezones)),
        default='US/Mountain',
    )
    is_followup = models.BooleanField(default=False)
    retain_numbers = models.BooleanField(default=False)
    skip_prospects_who_messaged = models.BooleanField(default=True)

    objects = CampaignManager()

    class Meta():
        app_label = 'sherpa'
        ordering = ['-id']

    def __str__(self):
        return self.name

    @property
    def block_reason(self):
        """
        Bulk sending can be blocked for a variety of reasons, defined by this property.
        """
        company = self.company
        if (company.subscription_status != Company.SubscriptionStatus.ACTIVE and not
                company.is_billing_exempt):
            return Company.BlockReason.SUBSCRIPTION
        if not self.market.has_sufficient_numbers:
            return Company.BlockReason.ACTIVE_NUMBERS
        if company.is_messaging_disabled:
            return Company.BlockReason.TIME
        return ''

    @property
    def upload_prospect_running(self):
        """
        If there's a running `UploadProspect` tied to this `Campaign`, return the id.
        """
        if not self.uploadprospects_set.filter(status='running'):
            return None
        return self.uploadprospects_set.filter(status='running').first().id

    @property
    def total_delivered(self):
        """
        Returns an integer of how many messages were delivered according to the batch stats.
        """
        queryset = self.statsbatch_set.all()
        total_delivered = queryset.aggregate(Sum('delivered'))
        return total_delivered.get('delivered__sum') or 0

    @property
    def total_sent(self):
        """
        Total number of messages that have been sent (non-skipped) for this campaign.
        """
        queryset = self.statsbatch_set.all()
        aggregated = queryset.aggregate(sent=Sum('send_attempt')).get('sent')

        if not aggregated:
            return 0
        return aggregated - self.campaign_stats.total_skipped

    def update_unread(self):
        """
        Update the campaign's unread sms flag depending on if it has unread campaign prospects.
        """
        has_unread = self.campaignprospect_set.filter(has_unread_sms=True).exists()

        # There are no more unread campaign prospects in the campaign, remove unread flag.
        if not has_unread and self.has_unread_sms:
            self.has_unread_sms = False
            self.save(update_fields=['has_unread_sms'])

    def update_access(self, access, user=None):
        """
        Update the access objects for the campaign.

        :param access set: A set of profile ids that should have access to the campaign.
        :param user User: The user that is performing the update to access.
        """

        # By default, if an empty access list is sent, give access to ALL current active users in
        # the company.
        if len(access) == 0:
            access = set(
                self.company.profiles.filter(user__is_active=True).values_list('pk', flat=True),
            )

        # Ensure that the request user is always included in the access.
        if user:
            access.add(user.profile.id)

        # Add the access users if they don't already have it.
        for profile_id in access:
            profile = UserProfile.objects.get(id=profile_id, company=self.company)
            CampaignAccess.objects.get_or_create(campaign=self, user_profile=profile)

        # Remove users that were not in the access list.
        remove_qs = CampaignAccess.objects.filter(
            campaign=self,
        ).exclude(user_profile__id__in=access)

        for campaign_access in remove_qs:
            campaign_access.delete()

    def create_followup(self, user, name, retain_numbers=False, retain_permissions=True):
        """
        Creates a new follow-up campaign from the original instance.

        Returns the newly created campaign instance.

        :param user User: The user that is generating the followup campaign.
        :param retain_numbers bool: This will determine if the new followup campaign will keep
        existing phone numbers instead of assigning new ones to the prospects.
        :param retain_permissions bool: Allows the followup campaign to keep the current user
        permissions from the original.
        """
        followup = Campaign.objects.create(
            name=name,
            company=self.company,
            created_by=user,
            timezone=self.timezone,
            market=self.market,
            is_followup=True,
            retain_numbers=retain_numbers,
            zapier_webhook=self.zapier_webhook or self.company.default_zapier_webhook,
            followup_from=self,
        )

        if retain_permissions:
            access = []
            for profile in self.campaignaccess_set.all().values_list('user_profile_id', flat=True):
                access.append(CampaignAccess(campaign=followup, user_profile_id=profile))
            if access:
                CampaignAccess.objects.bulk_create(access)

        return followup

    def update_progress(self):
        """
        Sometimes the campaign progress will become out of data and running this will look at all
        the sent and skipped messages and set the correct amount.
        """
        self.update_campaign_stats()

    def update_total_leads(self, increment):
        """
        Increment or decrement total leads.
        """
        val = 1 if increment else -1

        self.campaign_stats.total_leads = F('total_leads') + val
        self.campaign_stats.save(update_fields=['total_leads'])

    def update_has_priority(self):
        """
        Check if there are any campaign prospects that are marked as priority and update the
        priority count on the campaign.

        Returns boolean of if the campaign has a prospect with priority.
        """
        priority_count = self.campaignprospect_set.filter(prospect__is_priority=True).count()
        self.has_priority = priority_count > 0
        self.save(update_fields=['has_priority'])

        self.campaign_stats.total_priority = priority_count
        self.campaign_stats.save(update_fields=['total_priority'])

        return self.has_priority

    def update_campaign_stats(self):
        """
        Updates the campaigns stats.
        """
        from campaigns.tasks import (
            update_total_initial_sent_skipped_task,
            update_total_qualified_leads_count_task,
            record_skipped_send,
        )
        cs = self.campaign_stats
        counts = self.campaignprospect_set.values(
            'prospect__phone_type',
        ).order_by(
            'prospect__phone_type',
        ).annotate(c=Count(F('id')))
        self.campaignprospect_set.exclude(phone_type_synced='YES').update(phone_type_synced='YES')
        mobile = 0
        landline = 0
        other = 0
        for count in counts:
            if count['prospect__phone_type'] == 'mobile':
                mobile += count['c']
            elif count['prospect__phone_type'] == 'landline':
                landline += count['c']
            else:
                other += count['c']
        cs.total_mobile = mobile
        cs.total_landline = landline
        cs.total_phone_other = other
        cs.save(update_fields=['total_mobile', 'total_landline', 'total_phone_other'])
        update_total_initial_sent_skipped_task.delay(self.id)
        update_total_qualified_leads_count_task.delay(self.id)
        record_skipped_send.delay(self.id)

    def update_stats_batch(self):
        """
        After a message is sent or skipped the stats batch for the campaign is created or updated to
        record the stats of the message sent.
        """
        from sherpa.models import StatsBatch
        provider = Provider.TWILIO if self.market.name == 'Twilio' else Provider.TELNYX

        stats_batch_list = self.statsbatch_set.all()
        if not stats_batch_list:
            # No stats batch exists for the campaign.
            stats_batch = StatsBatch.objects.create(
                campaign=self,
                market=self.market,
                parent_market=self.market.parent_market,
                batch_number=1,
                provider=provider,
            )
        else:
            stats_batch = stats_batch_list.first()
            if stats_batch.send_attempt >= 100:
                # The latest stats batch is full, create a new one.
                batch_number = stats_batch.batch_number + 1
                stats_batch = StatsBatch.objects.create(
                    campaign=self,
                    market=self.market,
                    parent_market=self.market.parent_market,
                    batch_number=batch_number,
                    provider=provider,
                )

        with django_transaction.atomic():
            # Increment the stats batch.
            stats_batch = StatsBatch.objects.select_for_update().get(id=stats_batch.id)
            stats_batch.send_attempt = F('send_attempt') + 1
            stats_batch.last_send_utc = django_tz.now()
            stats_batch.save(update_fields=['send_attempt', 'last_send_utc'])

        return stats_batch

    def get_bulk_sent_messages(self, start_date=None, end_date=None):
        """
        Return a queryset of `SMSMessage` that had their initial send in the time range passed in.
        """
        from sherpa.models import SMSMessage
        queryset = SMSMessage.objects.filter(campaign=self)

        if start_date == end_date and start_date:
            # Filter for a single day.
            queryset = queryset.filter(dt__date=start_date)
        else:
            # Filter for a date range.
            if start_date:
                queryset = queryset.filter(dt__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(dt__date__lte=end_date)

        return queryset

    def get_prospect_activities(self, activity_title, start_date=None, end_date=None):
        """
        Return a queryset of the prospect activities for a single date or in a given time range.

        :param activity_title str: The type of activity that we're wanting to query on.
        """
        queryset = Activity.objects.filter(prospect__in=self.prospects, title=activity_title)

        if start_date == end_date and start_date:
            # Filter for a single day.
            queryset = queryset.filter(date_utc__date=start_date)
        else:
            # Filter for a date range.
            if start_date:
                queryset = queryset.filter(date_utc__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(date_utc__date__lte=end_date)

        return queryset

    def get_delivered_initial_messages(self, start_date=None, end_date=None):
        """
        Return a queryset of delivered messages for a single date or in a given time range.
        """
        queryset = self.smsmessage_set.filter(message_status='delivered')

        if start_date == end_date and start_date:
            # Filter for a single day.
            queryset = queryset.filter(dt__date=start_date)
        else:
            # Filter for a date range.
            if start_date:
                queryset = queryset.filter(dt__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(dt__date__lte=end_date)

        return queryset

    def get_delivery_rate(self, start_date=None, end_date=None):
        """
        Percentage of messages that were delivered as opposed to sent. Can optionally pass in a
        start date and end date to retrive a time-filtered delivery rate.

        Returns an integer between 0 and 100.
        """
        # When not filtering by dates, we can have improved performance by using the model fields.
        if not start_date and not end_date:
            return self.delivery_rate

        bulk_messages = self.get_bulk_sent_messages(start_date=start_date, end_date=end_date)
        if not bulk_messages.count():
            return 0
        delivered_messages = []

        for message in bulk_messages:
            if not message.is_delivered:
                continue
            delivered_messages.append(message)

        delivered_count = len(delivered_messages)
        sent_count = bulk_messages.count()
        return round(delivered_count / sent_count * 100)

    def get_responses(self, start_date=None, end_date=None):
        """
        Return a queryset of the first responses from prospects that were received in this campaign.
        """
        queryset = self.initialresponse_set.all()

        if start_date:
            queryset = queryset.filter(created__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created__date__lte=end_date)

        return queryset

    def get_response_rate(self, start_date=None, end_date=None):
        """
        Percentage of prospects that have responded to bulk messages in this campaign.

        Returns an integer between 0 and 100.
        """
        date_kwargs = {'start_date': start_date, 'end_date': end_date}
        bulk_messages = self.get_bulk_sent_messages(**date_kwargs)
        if not bulk_messages.count():
            return 0
        responses = self.get_responses(**date_kwargs)

        return round(responses.count() / bulk_messages.count() * 100)

    def get_skipped_count(self, start_date=None, end_date=None):
        """
        Return an integer for how many messages were skipped in a given day or date range.

        TODO: Ideally we have a record for each skipped with the datetime that it was skipped and
        other data (such as reason), however we don't have that yet and the best way to get skipped
        messages per-day is to look at the stats batches and have to just assume that all messages
        were sent on that same day as last sent.
        """
        queryset = self.statsbatch_set.all()

        if start_date == end_date:
            # Filter for a single day.
            queryset = queryset.filter(last_send_utc__date=start_date)
        else:
            # Filter for a date range.
            if start_date:
                queryset = queryset.filter(last_send_utc__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(last_send_utc__date__lte=end_date)

        # Aggregate the sum using the model property.
        total_skipped = 0
        for stats_batch in queryset:
            total_skipped += stats_batch.total_skipped

        return total_skipped

    def build_export_query(self, filters):
        """
        Generates a queryset based on possible export filters.

        :param filters dict: An object containing possible filters for the queryset.
        """
        queryset = self.campaignprospect_set.all()
        params = Q()

        lead_stage = filters.get('lead_stage', None)
        is_priority_unread = filters.get('is_priority_unread', False)
        phone_type = filters.get('phone_type', '')

        if is_priority_unread or lead_stage:
            if lead_stage:
                params &= Q(prospect__lead_stage=lead_stage)
            if is_priority_unread:
                params &= Q(Q(prospect__is_priority=True) | Q(prospect__has_unread_sms=True))
        else:
            search_phone_types = ['mobile', 'landline']
            if phone_type in search_phone_types:
                params &= Q(prospect__phone_type=phone_type)
            elif phone_type == 'other':
                params &= ~Q(prospect__phone_type__in=search_phone_types)
            elif phone_type == 'litigator':
                params &= Q(
                    Q(is_associated_litigator=True) | Q(is_litigator=True),
                )
            elif phone_type == 'dnc':
                params &= Q(prospect__do_not_call=True)
            else:
                pass

        return queryset.select_related('prospect').filter(params)

    @property
    def current_batch(self):
        return self.statsbatch_set.first()

    @property
    def current_batch_status(self):
        """
        DEPRECATED: Should use `current_batch` instead to get full object.

        Return data about where the campaign is for its current batch.

        :return: tuple of data for (batch_number, sent)
        """
        latest_batch = self.statsbatch_set.last()

        if not latest_batch:
            return 0, 0
        return latest_batch.batch_number, latest_batch.send_attempt

    @property
    def can_create_followup(self):
        """
        Campaigns can only create a follow-up if it was created before the threshold days for
        messaging prospects.

        If the campaign were to be created within the threshold days, all the prospects would be
        skipped.
        """
        cutoff_date = django_tz.now() - timedelta(days=self.company.threshold_days + 1)
        return self.created_date < cutoff_date

    @property
    def phone_number_count(self):
        # Phone number count is actually the amount of prospects...
        return self.total_prospects

    @property
    def delivery_rate(self):
        """
        Return the delivery rate for the entire campaign.
        """
        queryset = self.statsbatch_set.all()
        aggregated = queryset.aggregate(
            send_attempt=Sum('send_attempt'), delivered=Sum('delivered'))
        attempts = aggregated.get('send_attempt')
        if not attempts:
            sent_count = 0
        else:
            sent_count = attempts - self.campaign_stats.total_skipped
        delivered_count = aggregated.get('delivered') or 0
        return round(delivered_count / sent_count * 100) if sent_count else 0

    @property
    def prospects(self):
        """
        Return a queryset of `Prospect` instances that are in this campaign.
        """
        cp_queryset = self.campaignprospect_set.all()
        if self.is_direct_mail:
            cp_queryset = cp_queryset.filter(removed_datetime__isnull=True)
        return Prospect.objects.filter(id__in=cp_queryset.values_list('prospect_id', flat=True))

    @property
    def list_quality_score(self):
        """
        List quality is determined by the amount of verified owners vs the amount of responses.
        """
        verified_count = CampaignProspect.objects.filter(
            campaign=self,
            prospect__owner_verified_status='verified',
            has_responded_via_sms='yes',
        ).exclude(last_message_status='undelivered').count()
        response_count = self.get_responses().count()

        if response_count > 0:
            return round(verified_count / response_count * 100)

        return 0

    @property
    def total_properties(self):
        return self.campaignprospect_set.filter(
            Q(count_as_unique=True) | Q(include_in_upload_count=True)).count()

    @property
    def total_prospects(self):
        if self.is_direct_mail:
            return self.prospects.count()
        return CampaignProspect.objects.filter(Q(campaign=self)).count()

    @property
    def total_mobile_phones(self):
        return CampaignProspect.objects.filter(campaign=self, prospect__phone_type='mobile').count()

    @property
    def total_landline_phones(self):
        return CampaignProspect.objects.filter(
            campaign=self, prospect__phone_type='landline').count()

    @property
    def total_other_phones(self):
        return self.campaignprospect_set.exclude(
            prospect__phone_type__in=[None, 'mobile', 'landline'],
        ).count()

    @property
    def total_litigators(self):
        return CampaignProspect.objects.filter(
            Q(is_associated_litigator=True) | Q(is_litigator=True),
            campaign=self,
        ).count()

    @property
    def total_internal_dnc(self):
        return CampaignProspect.objects.filter(
            Q(is_associated_dnc=True) | Q(prospect__do_not_call=True),
            campaign=self,
        ).count()

    @property
    def delivered_response_rate(self):
        """
        Calculate the response rate on the delivered messages.
        """
        stats = self.campaign_stats
        if not stats.has_delivered_sms_only_count:
            return 0
        return round(self.get_responses().count() / stats.has_delivered_sms_only_count * 100)

    @property
    def sms_responses_count(self):
        """
        DEPRECATED: All references to sms response counts or rates should go through `get_responses`
        or `get_response_rate`.
        """
        return CampaignProspect.objects.filter(
            Q(has_responded_via_sms='yes'), Q(campaign=self),
        ).count()

    @property
    def response_rate_sms(self):
        """
        Determine the full response rate for the campaign.
        """
        total_messages_delivered = self.campaign_stats.has_delivered_sms_only_count
        total_sms_responses = self.sms_responses_count
        if total_sms_responses > 0 and total_messages_delivered > 0:
            return (float(total_sms_responses) / total_messages_delivered) * 100

        return 0

    @property
    def total_initial_sms_undelivered(self):
        """
        Returns a count of bulk messages that returned as undelivered.
        """
        # TODO: This should be updated to be aggregated.
        return 0

    @property
    def auto_dead_percentage(self):
        """
        Auto-dead percentage for the entire campaign using aggregated fields.

        For time-filtered auto-dead percentages, use `get_prospect_activities` with the appropriate
        activity title.
        """
        total_sms_responses = self.sms_responses_count
        total_auto_dead = self.campaign_stats.total_auto_dead_count
        return round(total_auto_dead / total_sms_responses * 100) if total_sms_responses else 0

    @property
    def skip_trace_cost(self):
        total_unique_uploads = CampaignProspect.objects.filter(
            Q(include_in_skip_trace_cost=True), Q(campaign=self),
        ).count()

        # default is  $0.07 per record
        if total_unique_uploads > 0:
            return float(total_unique_uploads) * float(self.skip_trace_cost_per_record)
        else:
            return 0

    @property
    def total_leads_generated(self):
        return CampaignProspect.objects.filter(
            prospect__is_qualified_lead=True, campaign=self).count()

    @property
    def priority_count(self):
        return self.campaignprospect.filter(prospect__is_priority=True).count()

    @property
    def percent_complete(self):
        """
        Return an integer of the percentage of the prospects that have been sent to or skipped in
        this campaign, for all eligible mobile phone numbers.

        If there are no prospects loaded with mobile numbers, then there should be nothing returned.
        """
        total_mobile = self.campaign_stats.total_mobile
        if not total_mobile:
            # When there are no prospects in the campaign yet, there should be no value.
            return None

        # It's possible to have a negative percent when follow-up campaigns are created.
        percent = round(self.campaign_stats.total_initial_sent_skipped / total_mobile * 100)
        return percent if percent >= 0 else 0

    @property
    def access_list(self):
        """
        Returns a list of users that has access to the campaign.  If ALL users within the company
        has access to the campaign, return an empty list.
        """
        company_users = set(self.company.profiles.values_list('pk', flat=True))
        campaign_users = set(self.campaignaccess_set.values_list('user_profile_id', flat=True))
        if company_users ^ campaign_users:
            return list(campaign_users)
        else:
            return []


class Prospect(models.Model):
    """
    Prospects are people that are contacted through campaigns.

    The data here in theory should be only data that is for all campaigns and data specific to
    campaigns would be in the `CampaignProspect` model, however in practice much of the data is
    duplicated.

    In the future this model will see a bunch of cleanup to get rid of all the duplicated data and
    only include data that should be shared for prospects across  all campaigns.
    """
    class OwnerVerifiedStatus:
        OPEN = 'open'
        VERIFIED = 'verified'
        UNVERIFIED = 'unverified'

        CHOICES = (
            (OPEN, 'Open'),
            (VERIFIED, 'Verified'),
            (UNVERIFIED, 'Unverified'),
        )

    class PhoneType:
        VOIP = 'voip'
        MOBILE = 'mobile'
        LANDLINE = 'landline'
        ERROR = 'error'
        NA = 'na'

        CHOICES = (
            (VOIP, 'VOIP'),
            (MOBILE, 'Mobile'),
            (LANDLINE, 'Landline'),
            (ERROR, 'Error'),
            (NA, 'Not Applicable'),
        )

    class LastMessageStatus:
        SENT = 'sent'
        FAILED = 'failed'
        DELIVERED = 'delivered'
        UNDELIVERED = 'undelivered'

        CHOICES = (
            (SENT, 'Sent'),
            (FAILED, 'Failed'),
            (DELIVERED, 'Delivered'),
            (UNDELIVERED, 'Undelivered'),
        )

    # TODO: (aww20191104) Company should be required, but 41603 prospects without company.
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    qualified_lead_created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE)

    # TODO: (aww20191125) These m2m fields should be removed, their existance is through the
    #       `CampaignPropsect` model.
    campaigns = models.ManyToManyField(Campaign, blank=True)
    markets = models.ManyToManyField('Market', blank=True)
    lead_stage = models.ForeignKey('LeadStage', null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(
        'prospects.ProspectTag', through='prospects.ProspectTagAssignment', blank=True)
    agent = models.ForeignKey(UserProfile, null=True, blank=True,
                              on_delete=models.SET_NULL)
    cloned_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    sherpa_phone_number_obj = models.ForeignKey(
        'sherpa.PhoneNumber', null=True, blank=True, on_delete=models.SET_NULL)

    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    last_modified = models.DateTimeField(null=True, blank=True)
    first_name = models.CharField(null=True, blank=True, max_length=255)
    last_name = models.CharField(null=True, blank=True, max_length=255)

    # TODO (aww20200908): blank/null only allowed initially until all prospects have been assigned
    #     their property. After that, it SHOULD be required and we can remove the property_* and
    #     mailing_* fields below.
    prop = models.ForeignKey('properties.Property', blank=True, null=True, on_delete=models.CASCADE)

    upload_duplicate = models.BooleanField(
        null=True,
        blank=True,
        help_text="If this was duplicated in two or more Skip Trace uploads, don't charge.",
    )

    property_address = models.TextField(null=True, blank=True)
    property_city = models.CharField(null=True, blank=True, max_length=255)
    property_state = models.CharField(null=True, blank=True, max_length=255)
    property_zip = models.CharField(null=True, blank=True, max_length=255)

    mailing_address = models.TextField(null=True, blank=True)
    mailing_city = models.CharField(null=True, blank=True, max_length=255)
    mailing_state = models.CharField(null=True, blank=True, max_length=255)
    mailing_zip = models.CharField(null=True, blank=True, max_length=255)

    custom1 = models.CharField(null=True, blank=True, max_length=512)
    custom2 = models.CharField(null=True, blank=True, max_length=512)
    custom3 = models.CharField(null=True, blank=True, max_length=512)
    custom4 = models.CharField(null=True, blank=True, max_length=512)

    # Data gathered about the prospect's phone. Can be removed once a relation to PhoneType is
    # setup.
    phone_raw = models.CharField(null=True, blank=True, max_length=255, db_index=True)
    phone_type = models.CharField(null=True, blank=True, max_length=16, choices=PhoneType.CHOICES)
    phone_carrier = models.CharField(null=True, blank=True, max_length=255)
    phone = models.ForeignKey(
        'PhoneType',
        blank=True,
        null=True,
        related_name='phone_type',
        on_delete=models.SET_NULL,
    )
    has_unread_sms = models.BooleanField(default=False, db_index=True)
    wrong_number = models.BooleanField(default=False)
    do_not_call = models.BooleanField(default=False)
    opted_out = models.BooleanField(null=True, blank=True)
    email = models.CharField(null=True, blank=True, max_length=255)
    is_priority = models.BooleanField(default=False, db_index=True)
    is_qualified_lead = models.BooleanField(default=False)
    qualified_lead_dt = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(null=True, blank=False)
    is_archived = models.BooleanField(null=True)

    # TODO: Transitional field. We're going to need to migrate all the uuids from the `token` field
    # to the `uuid_token` field, and then can remove the `token` field and add the default value. We
    # need to save the original token because of historical links that have been exported from
    # Sherpa.
    uuid_token = models.UUIDField(blank=True, null=True, db_index=True)

    # DEPRECATED: Token used to give a uuid identifier for public url retrieval.
    token = models.CharField(
        max_length=40, blank=True, null=True, default=uuid.uuid4, db_index=True)

    # Could move all the reminder data into a `ProspectReminder` model.
    has_reminder = models.BooleanField(default=False)
    reminder_date_local = models.DateTimeField(null=True, blank=True)
    reminder_date_utc = models.DateTimeField(null=True, blank=True, db_index=True)
    reminder_email_sent = models.BooleanField(default=False)
    reminder_agent = models.ForeignKey(
        UserProfile,
        related_name='reminder_agent',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # TODO: (aww20190823) change `has_responded_via_sms` to a BooleanField.
    has_responded_via_sms = models.CharField(null=True, blank=True, max_length=255)
    saved_to_zapier_dt = models.DateTimeField(null=True, blank=True)

    # Related record id shows a relation with multiple prospsects to the same skip trace property
    # and is set in the upload process. This should have been made as a relation to skip trace
    # property.
    related_record_id = models.CharField(null=True, blank=True, max_length=255, db_index=True)
    owner_verified_status = models.CharField(
        max_length=16,
        default=OwnerVerifiedStatus.OPEN,
        choices=OwnerVerifiedStatus.CHOICES,
    )
    emailed_lead_to_podio_dt = models.DateTimeField(null=True, blank=True)

    total_sms_sent_count = models.IntegerField(default=0)
    total_sms_received_count = models.IntegerField(default=0)
    last_sms_sent_utc = models.DateTimeField(null=True, blank=True)
    last_sms_received_utc = models.DateTimeField(null=True, blank=True)
    call_forward_number = models.CharField(null=True, blank=True, max_length=255)

    # Validated property fields, that should be moved to the Property model.
    validated_property_status = models.CharField(
        null=True, blank=True, max_length=16, db_index=True)
    validated_property_delivery_line_1 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_property_delivery_line_2 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_property_plus4_code = models.CharField(null=True, blank=True, max_length=16)
    validated_property_latitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_longitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_vacant = models.CharField(null=True, blank=True, max_length=16)

    tracker = FieldTracker(fields=[
        'first_name',
        'last_name',
        'phone_raw',
        'lead_stage_id',
        'is_blocked',
        'do_not_call',
        'is_priority',
        'is_qualified_lead',
        'wrong_number',
        'opted_out',
        'owner_verified_status',
        'is_archived',
        'prop_id',
        'last_sms_sent_utc',
        'last_sms_received_utc',
    ])
    objects = ProspectManager()

    class Meta:
        app_label = 'sherpa'
        ordering = ('id',)

    @property
    def is_verizon(self):
        if not self.phone_data or not self.phone_data.carrier:
            return False

        carrier = self.phone_data.carrier.lower()
        return any([
            'verizon' in carrier,
            'cellco' in carrier,
        ])

    @property
    def phone_formatted_display_calculated(self):
        """
        DEPRECATED: This should be removed and usage of self.phone_display instead.
        """
        return self.phone_display

    @property
    def full_number(self):
        """
        Returns the fully qualified number with country code.
        """
        return f'+1{self.phone_raw}' if self.phone_raw else ''

    @property
    def street_view_url(self):
        """
        Return the street view url if it's available.

        [Developer Guide](https://developers.google.com/maps/documentation/streetview/intro)
        """
        api_key = settings.GOOGLE_STREET_VIEW_API_KEY
        secret = settings.GOOGLE_STREET_VIEW_SECRET

        if not api_key or not secret or not self.address_display:
            return None

        # Generate the unsigned url to be used in generating the signature.
        location = f'?location={self.address_display}'
        size = '&size=500x500'
        key = f'&key={api_key}'

        # Now we can sign the url and return it.
        unsigned_url = f'/maps/api/streetview{location}{size}{key}'.replace(' ', '%20')
        return sign_street_view_url(unsigned_url, secret)

    @property
    def lead_stage_title(self):
        return self.lead_stage.lead_stage_title if self.lead_stage else ''

    @property
    def message_disable_reason(self):
        """
        For some prospects, their messaging should be disabled.
        """
        if self.is_verizon and not self.is_in_twilio_market and not self.is_in_inteliquent_market:
            return "The prospect's carrier is not accepting messages at this time."

        if not self.campaignprospect_set.exists():
            return "Not assigned to a campaign."

        return ""

    @property
    def latest_crm_activities(self):
        """
        Returns a queryset with the latest qualified & verified activities for the prospect, which
        represent the activities created from the crm action.
        """
        qualified_activity = Activity.objects.filter(
            prospect=self,
            title=Activity.Title.ADDED_QUALIFIED,
        ).last()
        verified_activity = Activity.objects.filter(
            prospect=self,
            title=Activity.Title.OWNER_VERIFIED,
        ).last()

        # Sometimes there might not be an activity.
        activity_id_list = []
        if qualified_activity:
            activity_id_list.append(qualified_activity.id)
        if verified_activity:
            activity_id_list.append(verified_activity.id)

        return Activity.objects.filter(id__in=activity_id_list)

    @property
    def mark_as_wrong_number(self):
        """
        Check if the prospect should be marked as wrong number, based on if it meets a threshold of
        other prospects with the same name and number marked as wrong number.

        :return: Boolean determining if the prospect should be marked as wrong number.
        """
        if not self.phone_raw or not self.first_name:
            return False

        queryset = Prospect.objects.filter(
            phone_raw=self.phone_raw,
            wrong_number=True,
            first_name=self.first_name,
        )
        return queryset.count() > 1

    @property
    def verified_status(self):
        return self.get_owner_verified_status_display()

    @property
    def profiles_with_access(self):
        """
        Returns a queryset of `UserProfile` of all the profiles that have access to this prospect.
        """
        campaign_id_list = self.campaignprospect_set.values_list('campaign', flat=True)
        profile_id_list = CampaignAccess.objects.filter(
            campaign__id__in=campaign_id_list,
        ).values_list('user_profile', flat=True).distinct()
        return UserProfile.objects.filter(id__in=profile_id_list)

    def modify_unread_count(self, value):
        """
        Increments or decrements the unread count of profiles with access to this prospect.

        :param value int: The value that we are going to modify the unread count by. This number can
            be either positive or negative, and typically always will be 1 or -1.
        """
        update_profiles = []
        for profile in self.profiles_with_access:
            # Don't allow going negative.
            if profile.unread_prospect_count == 0 and value < 0:
                continue
            profile.unread_prospect_count = F('unread_prospect_count') + value
            update_profiles.append(profile)

        UserProfile.objects.bulk_update(update_profiles, ['unread_prospect_count'])

    def is_carrier_template_verification_required(self, live_check=False):
        """
        Detect if the prospect's carrier requires SMS templates to be verified.

        DEPRECATED: All functionality around carrier-approved templates is being removed in favor of
            allowing custom templates but enforcing identification and opt out language.

        :param verify bool: Before attempting batch send we need to live check the carrier because
            some of our carriers are not up-to-date and we cannot send to AT&T templates that aren't
            carrier-approved.
        """
        return False

        phone_type = self.phone_data

        # Return false if prospect has not phone data
        if not phone_type:
            return False

        if live_check and not settings.TEST_MODE:
            client = TelnyxClient()
            phone_number = self.phone_raw
            phone_number_response = client.fetch_number(phone_number)
            carrier = phone_number_response.get('spid_carrier_name')

            if phone_type.carrier != carrier:
                phone_type.carrier = carrier
                phone_type.save(update_fields=['carrier'])

        # Returns false if prospect has no carrier information.
        if not phone_type.carrier:
            return False

        # List of carriers that require using approved SMS templates.
        carrier_list = [
            'cingular',
            'at&t',
            'at+t',
            'bellsouth',
        ]
        carrier = phone_type.carrier.lower()

        return any([sms_verify in carrier for sms_verify in carrier_list])

    @property
    def phone_data(self):
        """
        Return the `PhoneType` instance for this prospect's phone number if it exists.
        """
        from sherpa.models import PhoneType
        try:
            return PhoneType.objects.get(phone=self.phone_raw)
        except PhoneType.DoesNotExist:
            return None

    @property
    def call_forwarding_number(self):
        """
        When prospects call the sherpa number they are texting to, we need to forward that number to
        a relevant phone that an agent can pickup.

        There is a certain hierarchy of phone numbers that the prospect's call should be forwarded
        to:

        1) If there is an agent relay, then it should go to that number.
        2) If there is a call_forwarding_number on the campaign, it should go there.
        3) If there is a call_forwarding_number on the market, it should go there.
        4) If none of these exist, the call should just die.
        """
        if self.relay:
            return self.relay.agent_profile.phone

        # If the prospect is not part of any campaign, return nothing, if it is, get the newest.
        active_campaign = Campaign.objects.filter(
            campaignprospect__prospect=self,
        ).values(
            "call_forward_number",
            "market__call_forwarding_number",
        ).first()
        if not active_campaign:
            return

        # If the campaign has a valid forwarding number, forward there.
        campaign_number = active_campaign["call_forward_number"]
        if campaign_number and clean_phone(campaign_number):
            return campaign_number

        # If the market has a valid forwarding number, forward there.
        market_number = active_campaign["market__call_forwarding_number"]
        if market_number and clean_phone(market_number):
            return market_number

    @property
    def display_message(self):
        """
        Return the most recent `SMSMessage` instance received from the prospect.

        Will return by priority:
        1) Most recent message from prospect narrowed by last_sms_received_utc
        2) Most recent message from prospect (not narrowed by date)
        3) Most recent message to prospect.
        """
        messages = self.messages.all()

        if not messages.exists():
            return None

        messages = messages.order_by('-dt')

        messages_from_prospect = messages.filter(from_prospect=True)

        if self.last_sms_received_utc:
            # TODO There's a difference of a few milliseconds between dt and last_sms_received_utc.
            messages_from_prospect = messages_from_prospect.filter(
                dt__gte=self.last_sms_received_utc - timedelta(seconds=1),
            )

        return messages_from_prospect.first() or messages.first()

    @property
    def last_import_date(self):
        return self.campaignprospect_set.last().created_date

    @property
    def campaign_names(self):
        return ', '.join([c.name for c in self.campaign_qs])

    @property
    def last_sms_sent_local(self):
        dt = self.last_sms_sent_utc
        if dt:
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                dt.replace(tzinfo=pytz.utc)
            return dt.astimezone(pytz.timezone(self.company.timezone))
        return None

    @property
    def last_sms_received_local(self):
        dt = self.last_sms_received_utc
        if dt:
            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                dt.replace(tzinfo=pytz.utc)
            return dt.astimezone(pytz.timezone(self.company.timezone))
        return None

    @property
    def name(self):
        """
        DEPRECATED: Should use `get_full_name()` instead.
        """
        return "%s %s" % (self.first_name, self.last_name)

    @property
    def full_name(self):
        return self.get_full_name()

    @property
    def blank_name(self):
        """
        Return whether or not name is blank.
        """
        return not self.first_name or not self.last_name

    @property
    def phone_display(self):
        """
        Returns the prospect's phone number in preferred display format.
        """
        return number_display(self.phone_raw) if self.phone_raw else ""

    @property
    def address_display(self):
        """
        Format address to display or return blank if no address.
        """
        address = self.property_address if self.property_address else ''
        city = f"{self.property_city}," if self.property_city else ''
        state = self.property_state if self.property_state else ''
        zipcode = self.property_zip if self.property_zip else ''
        return f"{address} {city} {state} {zipcode}"

    @property
    def prefill_text_list(self):
        """
        Get list of quick replies by company and fill in by `msg_attrs`.
        """
        from sherpa.models import SMSPrefillText
        prefill_text_list_raw = SMSPrefillText.objects.filter(company=self.company).order_by(
            'sort_order')
        prefill_text_list = list()
        for prefill_text_raw in prefill_text_list_raw:
            prefill_text_template_object = SMSPrefillText(
                message=prefill_text_raw.message if prefill_text_raw.message else '',
                question=prefill_text_raw.question if prefill_text_raw.question else '',
                id=prefill_text_raw.id,
                company=self.company,
            )
            if prefill_text_raw.message:
                try:
                    message = prefill_text_raw.message
                    match = re.findall(r'(?<=\{CompanyName:)([^]]*?)(?=\})', message)
                    if match:
                        found_index = match[0]
                        i = int(match[0]) if match[0].isnumeric() else 0
                        if i >= len(self.company.outgoing_company_names):
                            i = 0
                        company_name = self.company.outgoing_company_names[i]
                        tag = '{CompanyName:' + found_index + '}'
                        message = message.replace(tag, company_name)
                    message_formatted = message.format(**self.msg_attrs)
                except (KeyError, ValueError):
                    message_formatted = prefill_text_raw.message

                prefill_text_template_object.message_formatted = message_formatted

            prefill_text_list.append(prefill_text_template_object)

        return prefill_text_list

    @property
    def emailed_to_podio(self):
        return True if self.emailed_lead_to_podio_dt else False

    @property
    def pushed_to_zapier(self):
        return True if self.saved_to_zapier_dt else False

    @property
    def total_view_link(self):
        if self.property_address is not None:
            # street = self.property_address.replace(" ", "-")
            street = self.property_address.replace(" ", "-")
        else:
            street = ""
        if self.property_city is not None:
            city = self.property_city.replace(" ", "+")
        else:
            city = ""
        if self.property_state is not None:
            state = self.property_state.replace(" ", "+")
        else:
            state = ""
        if self.property_zip is not None:
            zipcode = self.property_zip.replace(" ", "+")
        else:
            zipcode = ""
        return "http://www.totalviewrealestate.com/index.php?address=%s&city=%s&state=%s&zip=%s" % (
            street,
            city,
            state,
            zipcode,
        )

    @property
    def zillow_link(self):
        if self.property_address is not None:
            # street = self.property_address.replace(" ", "-")
            street = self.property_address.replace(" ", "-")
        else:
            street = ""
        if self.property_city is not None:
            city = self.property_city.replace(" ", "+")
        else:
            city = ""
        if self.property_state is not None:
            state = self.property_state.replace(" ", "+")
        else:
            state = ""
        if self.property_zip is not None:
            zipcode = self.property_zip.replace(" ", "+")
        else:
            zipcode = ""
        return "%s%s-%s-%s-%s%s" % (
            "https://www.zillow.com/homes/",
            street,
            city,
            state,
            zipcode,
            "_rb/",
        )

    @property
    def raw_address_to_validate_type(self):
        # Priorty = Full Address, Street + Zip, Street + City + State
        if all([self.property_address, self.property_city, self.property_state, self.property_zip]):
            return "full_address"
        elif self.property_address and self.property_zip:
            return "address_zip"
        elif self.property_address and self.property_city and self.property_state:
            return "address_city_state"
        else:
            return "no_address"

    @property
    def msg_attrs(self):
        # TODO verify live templates which tags are being used.
        return {
            'FirstName': self.first_name,
            'LastName': self.last_name,
            'StreetAddress': self.property_address,
            'PropertyStreetAddress': self.property_address,
            'PropertyAddressFull': self.address_display,
            'City': self.property_city,
            'State': self.property_state,
            'ZipCode': self.property_zip,
            'Custom1': self.custom1,
            'NAME': self.first_name,
            'ADDRESS': self.property_address,
            'CUSTOM1': self.custom1,
            'CompanyName': self.company.random_outgoing_company_name,
            'UserFirstName': self.company.random_outgoing_user_name,
        }

    @property
    def campaign_qs(self):
        """
        Return queryset of all the campaigns the prospect is in.
        """
        campaign_id_list = self.campaignprospect_set.values_list('campaign', flat=True)
        return Campaign.objects.filter(id__in=campaign_id_list)

    @property
    def is_in_twilio_market(self):
        """
        Return whether or not this Prospect is in a Twilio Market
        """
        return self.campaign_qs.filter(market__name='Twilio').exists()

    @property
    def is_in_inteliquent_market(self):
        """
        Return whether or not this Prospect is in a Inteliquent Market
        """
        return self.campaign_qs.filter(market__name='Inteliquent').exists()

    @property
    def relay(self):
        """
        Returns `ProspectRelay` related to this `Prospect`.
        """
        return self.prospectrelay_set.first()

    @property
    def sherpa_url(self):
        return settings.APP_URL + self.get_absolute_url()

    @property
    def public_url(self):
        first_campaign = self.campaign_qs.first()
        return f'{settings.APP_URL}/public/sms/{self.token}/{first_campaign.id}/'

    @property
    def is_absentee(self):
        return any([
            self.property_address != self.mailing_address,
            self.property_city != self.mailing_city,
            self.property_state != self.mailing_state,
        ])

    def apply_auto_tags(self, skip_trace=None, campaign_prospect=None):  # noqa: C901
        """
        Checks the prospect's data and adds the appropriate tags.
        """
        from prospects.models import ProspectTag
        from properties.models import PropertyTag

        # Setup configuration for what needs to be tagged.
        prospect_tags = []
        property_tags = []
        auto_tag_config = [
            {
                'validated_property_vacant': {
                    'type': PropertyTag,
                    'tag': 'Vacant',
                    'special_value_to_check': 'Y',
                },
                'is_absentee': {
                    'type': PropertyTag,
                    'tag': 'Absentee',
                    'special_value_to_check': None,
                },
                'obj': self,
            },
        ]
        # By default we check for the existence of a value (or a Boolean True) to decide to tag.
        # `special-value_to_check` indicates if we should check for a specific value instead.
        # Add configuration for auto tagging `Prospects` created from skip trace.
        if skip_trace:
            auto_tag_config.append(
                {
                    'returned_judgment_date': {
                        'type': PropertyTag,
                        'tag': 'Judgement',
                        'special_value_to_check': None,
                    },
                    'golden_address_lines': {
                        'type': PropertyTag,
                        'tag': 'Golden Address',
                        'special_value_to_check': None,
                    },
                    'deceased': {
                        'type': PropertyTag,
                        'tag': 'Probate / Death',
                        'special_value_to_check': 'True',
                    },
                    'bankruptcy': {
                        'type': PropertyTag,
                        'tag': 'Bankruptcy',
                        'special_value_to_check': None,
                    },
                    'returned_lien_date': {
                        'type': PropertyTag,
                        'tag': 'Lien',
                        'special_value_to_check': None,
                    },
                    'returned_foreclosure_date': {
                        'type': PropertyTag,
                        'tag': 'Pre-foreclosure',
                        'special_value_to_check': None,
                    },
                    'obj': skip_trace,
                },
            )
        # Add configuration for auto tagging `Prospects` using data from campaign prospect.
        if campaign_prospect:
            auto_tag_config.append(
                {
                    'is_litigator': {
                        'type': ProspectTag,
                        'tag': 'Litigator',
                        'special_value_to_check': None,
                    },
                    'is_associated_litigator': {
                        'type': ProspectTag,
                        'tag': 'Litigator Associate',
                        'special_value_to_check': None,
                    },
                    'obj': campaign_prospect,
                },
            )

        # Loop through the configuration and tag if applicable.
        for config in auto_tag_config:
            for key in config:
                if key != 'obj':
                    value_to_check = getattr(config['obj'], key)
                    add_tag = True if value_to_check else False
                    if config[key]['special_value_to_check']:
                        add_tag = value_to_check == config[key]['special_value_to_check']
                    if add_tag:
                        tag, _ = config[key]['type'].objects.get_or_create(
                            name=config[key]['tag'],
                            company=self.company,
                        )
                        if config[key]['type'] is ProspectTag:
                            prospect_tags.append(tag.id)
                        else:
                            property_tags.append(tag.id)

        # Add tags to this `Prospect`.
        if prospect_tags:
            self.tags.add(*prospect_tags)
        if property_tags and self.prop:
            self.prop.tags.add(*property_tags)

    def get_full_name(self):
        """
        Return the prospect's full name.

        This should be used instead of "fullname" which will be removed as a database field. Instead
        of using f-strings here, we need to take into account that first_name or last_name might be
        None (i.e. in the case of LLC).
        """
        full_name = str(self.first_name or '') + ' ' + str(self.last_name or '')
        if full_name == ' ':
            full_name = "Property Owner"
        return full_name.strip()

    def get_messages(self, only_delivered=True):
        """
        Returns a queryset of `SMSMessage` that are attached to this prospect.

        :param only_delivered bool: Determines if we want to return all messages or just the
                                    delivered ones.
        """
        queryset = self.company.smsmessage_set.filter(
            contact_number=self.full_number,
        ).order_by('dt')

        if only_delivered:
            queryset = queryset.exclude(message_status=self.LastMessageStatus.UNDELIVERED)

        return queryset

    def mark_as_read(self):
        """
        Set all the related data (self, campaign prospects, campaigns, message) to the prospect to
        be read.
        """
        # All the messages from the prospect should be marked as read.
        unread_messages = self.messages.filter(from_prospect=True, unread_by_recipient=True)
        unread_messages.update(unread_by_recipient=False)

        # Update the campaign prospects to be read.
        campaign_prospects = self.campaignprospect_set.all().prefetch_related('campaign')
        campaign_prospects.update(has_unread_sms=False)

        # Update the campaigns to be read, if this is the last unread prospect.
        campaign_list = set()
        for campaign_prospect in campaign_prospects:
            campaign_list.add(campaign_prospect.campaign)

        for campaign in campaign_list:
            campaign.update_unread()

        # Refresh the instance and decrement unread if needed, need to lock the instnace so we know
        # it doesn't get duplicated if multiple people mark as read at same time.
        with django_transaction.atomic():
            locked_instance = Prospect.objects.select_for_update().get(id=self.id)
            if locked_instance.has_unread_sms:
                locked_instance.has_unread_sms = False
                locked_instance.save(update_fields=['has_unread_sms'])
                self.modify_unread_count(-1)

    def build_bulk_message(self, sms_template, is_carrier_approved=False, sender_name=None, campaign=None):  # noqa: C901, E501
        """
        Pass in the raw message for the bulk message and transform it replacing with the values from
        the prospect.

        NOTE: This seems to be better suited as a SMSTemplate method.
        """
        message_raw = sms_template.message
        use_alternate_sms_template = False

        tags = get_tags(message_raw)
        for tag in get_tags(message_raw):
            if TAG_MAPPINGS[tag] and not getattr(self, TAG_MAPPINGS[tag]):
                use_alternate_sms_template = True
                break

        if not use_alternate_sms_template:
            if 'CompanyName' in tags:
                # Locate the possible index we will use.
                match = re.findall(r'(?<=\{CompanyName:)([^]]*?)(?=\})', message_raw)
                if match:
                    i = int(match[0]) if match[0].isnumeric() else 0
                    if len(self.company.outgoing_company_names) <= i:
                        use_alternate_sms_template = True
                elif not self.company.random_outgoing_company_name:
                    use_alternate_sms_template = True
            elif 'UserFirstName' in tags and not any([
                self.company.use_sender_name and sender_name,
                self.company.random_outgoing_user_name,
            ]):
                use_alternate_sms_template = True

        # Checking if (and which) opt out language should be used
        in_twilio_market = campaign and campaign.market.name == 'Twilio'
        exclude_opt_out_language = in_twilio_market and not self.company.enable_optional_opt_out
        postfix_message = ''
        if not exclude_opt_out_language:
            postfix_message = OPT_OUT_LANGUAGE_TWILIO if in_twilio_market else OPT_OUT_LANGUAGE

        # Either use the formatted message or the alternate template if the data isn't available.
        if use_alternate_sms_template:
            return sms_template.get_alternate_message(is_carrier_approved, postfix_message)

        # If 'use_sender_name' is turned on then fill in the template with 'sender_name'.
        # This overrides the default behavior of filling this in with 'outgoing_first_name'.
        if 'UserFirstName' in tags and self.company.use_sender_name and sender_name:
            message_raw = message_raw.replace('{UserFirstName}', sender_name)

        # As a template can now choose a company to use instead of a random one, we need to handle
        # that before sending to the msg_attrs.
        match = re.findall(r'(?<=\{CompanyName:)([^]]*?)(?=\})', message_raw)
        if match:
            found_index = match[0]
            i = int(match[0]) if match[0].isnumeric() else 0
            if i >= len(self.company.outgoing_company_names):

                i = 0
            company_name = self.company.outgoing_company_names[i]
            tag = '{CompanyName:' + found_index + '}'
            message_raw = message_raw.replace(tag, company_name)

        return message_raw.format(**self.msg_attrs).replace("None", "") + postfix_message

    @property
    def has_valid_sherpa_number(self):
        """
        Indicates whether Prospect currently has a phone that's not released.
        """
        from sherpa.models import PhoneNumber
        phone = self.sherpa_phone_number_obj
        return phone and phone.status != PhoneNumber.Status.RELEASED

    def send_message(self, message, user):  # noqa C901
        """
        Send an SMS message to a prospect.

        This is used for when sending individual messages, not when sending bulk messages.

        :param str message: The raw message that should be sent to the campaign prospect.
        :param User user: `User` instance that is sending the message.
        """
        from sherpa.models import SMSMessage
        from sms.tasks import track_sms_reponse_time_task

        profile = UserProfile.objects.get(user=user)
        company = self.company

        # Use the most recent campaign prospect for the prospect.
        cp = self.campaignprospect_set.first()

        # Get the sherpa phone number to use for sending to the prospect.
        if not self.sherpa_phone_number_obj:
            cp.assign_number()
            self.refresh_from_db()

        # If we are trying to send to a Verizon phone with a non Twilio number and this
        # Prospect is in a Twilio Market, assign a Twilio number.
        assign_twilio_number = all([
            self.is_in_twilio_market,
            self.sherpa_phone_number_obj.provider != Provider.TWILIO,
            self.is_verizon,
        ])
        if not self.has_valid_sherpa_number or assign_twilio_number:
            if assign_twilio_number:
                cp = self.campaignprospect_set.filter(campaign__market__name='Twilio').first()
            else:
                cp = self.campaignprospect_set.first()
            cp.assign_number()
            self.refresh_from_db()

        # If we still don't have a valid number, we don't want to send a message
        if not self.has_valid_sherpa_number:
            return

        our_number = f'+1{self.sherpa_phone_number_obj.phone}'
        contact_number = f'+1{self.phone_raw}'
        client = self.sherpa_phone_number_obj.client
        message_response = client.send_message(
            to=contact_number,
            from_=our_number,
            body=message,
        )

        # TODO: Redesign this
        provider = self.sherpa_phone_number_obj.provider
        message_id = None
        if provider == Provider.TELNYX:
            message_id = message_response.id
        elif provider == Provider.TWILIO:
            message_id = message_response.sid
        elif provider == Provider.INTELIQUENT:
            message_id = message_response.get('sid')
        SMSMessage.objects.create(
            our_number=our_number,
            contact_number=contact_number,
            from_number=our_number,
            to_number=contact_number,
            message=message,
            provider_message_id=message_id,
            prospect=self,
            company=company,
            user=user,
        )

        # Assign agent if none has been assigned.
        if not self.agent:
            self.agent = profile
        # Update stats about sending the prospect a message.
        self.last_sms_sent_utc = django_tz.now()
        self.save(update_fields=['last_sms_sent_utc', 'agent'])

        for cp in self.campaignprospect_set.all():
            # Update that the campaign prospects have been sent and not skipped.
            if not cp.sent and cp.skipped:
                cp.sent = True
                cp.skipped = False
                cp.save(update_fields=['sent', 'skipped'])
            elif not cp.sent:
                cp.sent = True
                cp.save(update_fields=['sent'])

        track_sms_reponse_time_task.delay(self.id, user.id)

    def get_absolute_url(self):
        """
        Return the url to the prospect page for the latest campaign prospect.
        """
        return f'/prospect/{self.id}/details'

    def __str__(self):
        return "%s %s" % (self.first_name, self.last_name)

    def set_lead_stage(self):
        """
        After a campaign prospect is sent a message, we need to update its leadstage to the initial
        message sent lead stage.
        """
        if self.lead_stage:
            return

        try:
            lead_stage = LeadStage.objects.get(
                company=self.company,
                lead_stage_title='Initial Message Sent',
            )
            if lead_stage:
                self.lead_stage = lead_stage
                self.save(update_fields=['lead_stage'])

        except LeadStage.DoesNotExist:
            return

    def toggle_do_not_call(self, user, value, index_update=True):
        """
        Toggle 'do_not_call' and log activity with given `User`.
        """
        # If the do_not_call is already the same as value we quit, got nothing to do
        if self.do_not_call == value:
            return self, []

        self.do_not_call = value
        update_fields = ['do_not_call']

        if value:
            # Set the prospect's lead stage to dead.
            self.lead_stage = self.company.leadstage_set.get(lead_stage_title="Dead")
            update_fields.append('lead_stage')

            # Mark the prospect's messages as read.
            self.mark_as_read()

        self.save(index_update=index_update, update_fields=update_fields)

        verb = "Added to" if value else "Removed from"
        actor = user.get_full_name() if user else "system"
        activity = Activity.objects.create(
            title=Activity.Title.ADDED_DNC if value else Activity.Title.REMOVED_DNC,
            prospect=self,
            description=f'{verb} Do Not Call list by {actor}',
            icon="fa fa-plus-circle" if value else "fa fa-minus-circle",
        )
        return self, [activity]

    def toggle_wrong_number(self, user=None, value=False, index_update=True):
        """
        Toggle 'wrong_number' and log activity with given `User`.
        """
        self.wrong_number = value
        update_fields = ['wrong_number']

        if value:
            # Set the prospect's lead stage to dead.
            self.lead_stage = self.company.leadstage_set.get(lead_stage_title="Dead")
            update_fields.append('lead_stage')

            # Mark the prospect's messages as read.
            self.mark_as_read()

        self.save(index_update=index_update, update_fields=update_fields)

        description_name = user.get_full_name() if user else 'system'
        activity = Activity.objects.create(
            title=Activity.Title.ADDED_WRONG if value else Activity.Title.REMOVED_WRONG,
            prospect=self,
            description=f'{"Set " if value else "Unset "} wrong number by {description_name}',
            icon="fa fa-plus-circle" if value else "fa fa-minus-circle",
        )
        return self, [activity]

    def toggle_is_priority(self, user, value, index_update=True):
        """
        Toggle 'is_priority' and log activity with given `User`.

        :param user user: the user that is performinbg the action.
        :param value: True/False determines if we're setting to qualified or removing.
        :return: Returns a tuple of the prospect and created activities
        """
        self.is_priority = value
        self.save(index_update=index_update, update_fields=['is_priority'])

        for campaign_prospect in self.campaignprospect_set.all().prefetch_related('campaign'):
            campaign_prospect.campaign.update_has_priority()

        activity = Activity.objects.create(
            title=Activity.Title.ADDED_PRIORITY if value else Activity.Title.REMOVED_PRIORITY,
            prospect=self,
            description=f'{"Added" if value else "Removed"} as a priority by'
                        f' {user.get_full_name()}',
            icon="fa fa-plus-circle" if value else "fa fa-minus-circle",
        )
        activities = [activity]

        # Giver ownership if this is a priority.
        if self.owner_verified_status != self.OwnerVerifiedStatus.VERIFIED and value:
            prospect, verified_activities = self.toggle_owner_verified(
                user, self.OwnerVerifiedStatus.VERIFIED, index_update=index_update)
            for verified_activity in verified_activities:
                activities.append(verified_activity)
        return self, activities

    def toggle_owner_verified(self, user, value, index_update=True):
        """
        Toggle 'owner_verified_status' and log activity with given `User`.

        :param user user: the user that is performinbg the action.
        :param value: True/False determines if we're setting to qualified or removing.
        :return: Returns a tuple of the prospect and created activity
        """
        self.owner_verified_status = value
        self.save(index_update=index_update, update_fields=['owner_verified_status'])

        verified = value == Prospect.OwnerVerifiedStatus.VERIFIED

        description = 'Owner verified by system'
        if user:
            description = f'Owner {"un" if not verified else ""}verified by {user.get_full_name()}'

        activity = Activity.objects.create(
            title=Activity.Title.OWNER_VERIFIED if verified else Activity.Title.OWNER_UNVERIFIED,
            prospect=self,
            description=description,
            icon="fa fa-plus-circle" if verified else 'fa fa-unlink',
        )

        # Mark related `Prospect`s as 'unverified' if prospect is verified.
        if self.related_record_id and verified:
            lead_stage = LeadStage.objects.get(lead_stage_title="Dead", company=self.company)
            for p in Prospect.objects.filter(
                    related_record_id=self.related_record_id,
            ).exclude(id=self.id):
                p.owner_verified_status = Prospect.OwnerVerifiedStatus.UNVERIFIED
                p.lead_stage = lead_stage
                p.wrong_number = True
                p.save(
                    index_update=index_update,
                    update_fields=['owner_verified_status', 'lead_stage', 'wrong_number'],
                )

                description = 'Owner set to not valid by system'
                if user:
                    description = f'Owner set to not valid by {user.get_full_name()}'
                Activity.objects.create(
                    title="Owner Not Valid",
                    prospect=p,
                    description=description,
                    icon="fa fa-times-circle",
                )

            # Mark related `CampaignProspect` objects as 'skipped'
            related_prospects = Prospect.objects.filter(
                related_record_id=self.related_record_id).exclude(id=self.id)
            for prospect in related_prospects:
                for cp in prospect.campaignprospect_set.filter(sent=False, skipped=False):
                    cp.skipped = True
                    cp.save(update_fields=['skipped'])

        return self, [activity]

    def toggle_qualified_lead(self, user, value, index_update=True):
        """
        Toggle 'is_qualified_lead' and log activity with given `User`.

        :param user user: the user that is performinbg the action.
        :param value: True/False determines if we're setting to qualified or removing.
        :return: Returns a tuple of the prospect and created activity
        """
        if self.is_qualified_lead and value:
            # The prospect is already qualified.
            return self, None

        self.is_qualified_lead = value
        self.qualified_lead_dt = None
        self.qualified_lead_created_by = None
        if self.is_qualified_lead:
            now = django_tz.now()
            self.qualified_lead_dt = now
            self.qualified_lead_created_by = user

        self.save(
            index_update=index_update,
            update_fields=[
                'is_qualified_lead',
                'qualified_lead_dt',
                'qualified_lead_created_by',
            ],
        )

        for campaign_prospect in CampaignProspect.objects.filter(prospect=self):
            campaign_prospect.campaign.update_total_leads(increment=value)

        activity = Activity.objects.create(
            title=Activity.Title.ADDED_QUALIFIED if value else Activity.Title.REMOVED_QUALIFIED,
            prospect=self,
            description=f'{"Added" if value else "Removed"} as a qualified lead by '
                        f'{user.get_full_name()}',
            icon="fa fa-plus-circle" if value else "fa fa-minus-circle",
        )
        activities = [activity]

        # Giver ownership if this is a qualified lead.
        if self.owner_verified_status != self.OwnerVerifiedStatus.VERIFIED and value:
            _, verified_activities = self.toggle_owner_verified(
                user, self.OwnerVerifiedStatus.VERIFIED, index_update=index_update)
            for verified_activity in verified_activities:
                activities.append(verified_activity)
        return self, activities

    def toggle_autodead(self, value, user=None):
        """
        Need to create an activity for when we're changing the auto-dead of a prospect.

        Auto-dead is only added by the system if the message is perceived as negative and the
        prospect should be marked as dead automatically. The auto-dead can be removed by users, in
        which case the user is passed in through the kwarg.

        :param bool value: True if we are adding to auto dead, false if not.
        :param User user: User that is performing the toggle action.
        """
        title = Activity.Title.ADDED_AUTODEAD if value else Activity.Title.REMOVED_AUTODEAD
        if value:
            description = 'Auto-dead added by system'
        elif user:
            description = f'Auto-dead removed by {user.get_full_name()}'
        else:
            description = 'Auto-dead removed by system'

        Activity.objects.create(prospect=self, title=title, description=description)
        if value:
            self.lead_stage = self.company.leadstage_set.get(lead_stage_title='Dead (Auto)')
        self.save(update_fields=['lead_stage'])

    def is_prospect_new(self, full_name, property_address, mailing_address):
        """
        Verify if the prospect that was found (via their phone number) is actually new prospect
        based on either their name, property address, or mailing address.  If any one of these
        fail their check, the prospect should be considered new.

        Both address dicts must contain an _address, _city, _state, _zip key prefixed with the
        type (property_city vs mailing_city).

        :param string full_name: Fullname of incoming prospect to check against.
        :param dict property_address: A dict containing incoming prospects property address.
        :param dict mailing_address: A dict containing incoming prospects mailing address.
        :returns bool:
        """
        if self.get_full_name() != full_name:
            return True

        property_address_check = [
            self.property_address != property_address['street'],
            self.property_city != property_address['city'],
            self.property_state != property_address['state'],
            self.property_zip != property_address['zip'],
        ]

        if any(property_address_check):
            return True

        mailing_address_check = [
            self.mailing_address != mailing_address['street'],
            self.mailing_city != mailing_address['city'],
            self.mailing_state != mailing_address['state'],
            self.mailing_zip != mailing_address['zip'],
        ]

        if any(mailing_address_check):
            return True

        return False

    def upload_prospect_tasks(self, upload, sort_order, is_new_prospect, has_litigator_list):
        """
        If `UploadProspect` was used to create `Prospect`s, then push to campaign associated with
        upload and update upload stats.

        :param upload: `UploadProspect` object
        :param sort_order: Integer (1 indicates first associated record).
        :param is_new_prospect: Boolean to indicate `Prospect` is new
        :param has_litigator_list: Boolean to indicate if associated record is a litigator
        """

        # Update upload related stats.
        if upload:
            upload.update_upload_stats(self, is_new_prospect)
        if not upload or not upload.campaign:
            return None, sort_order + 1

        # If campaign passed, push to campaign. Can create `Prospect` without this step.
        campaign_prospect, is_new_campaign_prospect = self.push_to_campaign(
            upload.campaign,
            is_new_prospect,
            has_litigator_list,
            sort_order,
        )

        # Add upload to CampaignProspect.
        if campaign_prospect:
            # Add `UploadProspect` object to `CampaignProspect`
            try:
                campaign_prospect.upload_prospects.add(upload)
            except IntegrityError:
                pass

        return campaign_prospect, sort_order + 1

    def update_phone_type_and_carrier(self):
        """
        Update phone type and carrier for this prospect's phone.
        """
        from sherpa.models import PhoneType
        if self.phone_type or settings.TEST_MODE:
            return

        phone_type_record, is_new_phone_type_record = PhoneType.objects.get_or_create(
            phone=self.phone_raw)

        # If this is a new `PhoneType`, run lookup to get type & carrier.
        error = None
        if is_new_phone_type_record or phone_type_record.carrier is None:
            error = phone_type_record.lookup_phone_type()

        # Set phone type and carrier to match `PhoneType` record (deprecated in future?)
        # Set to error message if there was an error on lookup. Set to 'na' if blank.
        phone_type = phone_type_record.type if not error else 'error on lookup'
        self.phone_type = 'na' if not phone_type else phone_type
        self.phone_carrier = phone_type_record.carrier if not error else 'error on lookup'

        self.save(update_fields=['phone_type', 'phone_carrier'])

    def push_to_campaign(
            self,
            campaign,
            is_new_prospect,
            has_litigator_list=False,
            sort_order=1,
            sms=True,
    ):
        """
        Push to campaign passed.
        """
        from sherpa.models import LitigatorList
        campaign_prospect, is_new_campaign_prospect = CampaignProspect.objects.get_or_create(
            campaign=campaign,
            prospect=self,
        )
        campaign_prospect.sort_order = sort_order
        update_fields = ['sort_order']

        # If DNC or set of phones used to create prospect has a litigator in it, mark as skipped.
        if has_litigator_list or self.do_not_call:
            campaign_prospect.skipped = True
            update_fields.append('skipped')

        # If phone found in `LitigatorList` mark as litigator.
        if LitigatorList.objects.filter(phone=self.phone_raw).exists():
            campaign_prospect.is_litigator = True
            update_fields.append('is_litigator')
        elif has_litigator_list:
            # If set of phones used to create prospect has a litigator, but this number is not a
            # litigator, mark this associated litigator.
            campaign_prospect.is_associated_litigator = True
            update_fields.append('is_associated_litigator')

        campaign_prospect.save(update_fields=update_fields)

        # We don't need to do the remaining sms related tasks if this is a direct mail campaign.
        if not sms or campaign.is_direct_mail:
            return campaign_prospect, is_new_campaign_prospect

        # Check if we should count this Prospect for charging.
        campaign_prospect.count_prospect(sort_order == 1, is_new_prospect, is_new_campaign_prospect)

        self.update_phone_campaign(campaign)

        self.wrong_number = self.mark_as_wrong_number
        self.save(update_fields=['wrong_number'])

        return campaign_prospect, is_new_campaign_prospect

    def update_phone_campaign(self, campaign):
        """
        Add campaign to PhoneType
        """
        from sherpa.models import PhoneType
        # Update campaign on phone type
        phone_type, _ = PhoneType.objects.get_or_create(phone=self.phone_raw)
        phone_type.campaign = campaign
        phone_type.save(update_fields=['campaign'])

    def update_propstack_listing(self):
        """
        Updates the prospects and properties propstack listing.
        """
        from search.tasks import stacker_full_update
        prop_id = [self.prop_id] if self.prop_id else []
        stacker_full_update.delay([self.id], prop_id)

    @property
    def skiptrace(self):
        filters = Q(returned_phone_1=self.phone_raw) | Q(returned_phone_2=self.phone_raw) | \
            Q(returned_phone_3=self.phone_raw)
        skiptrace_property = SkipTraceProperty.objects.filter(
            filters,
            prop__company=self.company,
        ).first()

        return skiptrace_property

    def save(self, index_update=True, *args, **kwargs):
        if self.tracker.has_changed('do_not_call'):
            if self.do_not_call:
                try:
                    # It is possible on the data level that `InternalDNC` instances are duplicated.
                    InternalDNC.objects.get_or_create(
                        phone_raw=self.phone_raw, company=self.company)
                except MultipleObjectsReturned:
                    pass
            else:
                InternalDNC.objects.filter(phone_raw=self.phone_raw, company=self.company).delete()
        self.last_modified = django_tz.now()

        if index_update and self.tracker.changed() and self.pk:
            self.update_propstack_listing()
        return super(Prospect, self).save(*args, **kwargs)


class CampaignProspect(models.Model):
    """
    Prospects can be part of campaigns.

    From a data perspective, a prospect can be part of many campaigns. However in practice, most of
    the time a prospect is only in 1 campaign. When creating a follow-up campaign the campaign
    prospect has its data reset and moved to the new campaign (still just in 1 campaign).

    I believe if the same prospect is uploaded to multiple campaigns then it could be part of
    multiple campaigns. There is much duplicated data and prospects will see much cleanup over time.
    """
    class SkipReason:
        THRESHOLD_MESSAGE = 'threshold'
        HAS_RESPONDED = 'has_responded'
        COMPANY_DNC = 'company_dnc'
        PUBLIC_DNC = 'public_dnc'
        LITIGATOR = 'litigator'
        SMS_RECEIPT = 'has_receipt'
        FORCED = 'forced'
        OPT_OUT_REQUIRED = 'opt_out_required'
        OPTED_OUT = 'opted_out'
        ATT = 'carrier_att'
        VERIZON = 'carrier_verizon'
        CARRIER = 'carrier'
        OUTGOING_NOT_SET = 'outgoing_not_set'
        WRONG_NUMBER = 'wrong_number'

        CHOICES = (
            (THRESHOLD_MESSAGE, 'Threshold'),
            (HAS_RESPONDED, 'Has responded previously'),
            (COMPANY_DNC, 'Company DNC'),
            (PUBLIC_DNC, 'Public DNC'),
            (LITIGATOR, 'Litigator'),
            (SMS_RECEIPT, 'Has SMS Receipt'),
            (FORCED, 'Forced'),
            (OPT_OUT_REQUIRED, 'Opt-out required'),
            (ATT, 'AT&T'),
            (VERIZON, 'Verizon'),
            (OUTGOING_NOT_SET, 'Outgoing not set'),
            (WRONG_NUMBER, 'Wrong number'),
            (CARRIER, 'Carrier'),
        )

    class BulkToggleActions:
        DNC = 'dnc'
        PRIORITY = 'priority'
        VERIFY = 'verify'
        VIEWED = 'viewed'

        CHOICES = (
            (DNC, 'DNC'),
            (PRIORITY, 'Priority'),
            (VERIFY, 'Verify'),
            (VIEWED, 'Viewed'),
        )

        TOGGLE_METHODS = {
            DNC: {
                'method': 'toggle_do_not_call',
                'value': False,
                'object': 'Prospect',
            },
            PRIORITY: {
                'method': 'toggle_is_priority',
                'value': True,
                'object': 'Prospect',
            },
            VERIFY: {
                'method': 'toggle_owner_verified',
                'value': Prospect.OwnerVerifiedStatus.VERIFIED,
                'object': 'Prospect',
            },
            VIEWED: {
                'method': 'mark_as_viewed',
                'value': True,
                'object': 'CampaignProspect',
            },
        }

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE)

    sms_template = models.ForeignKey('SMSTemplate', null=True, blank=True, on_delete=models.CASCADE)
    sms_carrier_approved_template = models.ForeignKey(
        'sms.CarrierApprovedTemplate',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    from_upload_skip_trace = models.ForeignKey(
        UploadSkipTrace, null=True, blank=True, on_delete=models.CASCADE)
    stats_batch = models.ForeignKey('StatsBatch', null=True, blank=True, on_delete=models.CASCADE)
    upload_prospects = models.ManyToManyField('UploadProspects', blank=True)

    created_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True, null=True, blank=True)

    scheduled = models.BooleanField(default=False)
    skipped = models.BooleanField(default=False)
    skip_reason = models.CharField(blank=True, max_length=16, choices=SkipReason.CHOICES)
    sent = models.BooleanField(default=False)
    has_unread_sms = models.BooleanField(default=False, db_index=True)
    sort_order = models.IntegerField(default=1, null=True, blank=True)
    include_in_skip_trace_cost = models.BooleanField(default=False)
    has_been_viewed = models.BooleanField(default=False)
    include_in_upload_count = models.BooleanField(default=False)
    is_litigator = models.BooleanField(default=False)
    is_associated_litigator = models.BooleanField(default=False)

    # These fields used for identifying the prospect is removed from dm campaign or not.
    removed_datetime = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(UserProfile, on_delete=models.CASCADE, null=True, blank=True)

    tracker = FieldTracker(fields=[
        'sent',
        'skipped',
        'has_responded2',
        'has_responded_dead_auto2',  # why 2..?
        'last_outbound_call',
        'last_inbound_call',
    ])

    # Theis needs to be converted to a boolean field.
    has_responded_via_sms = models.CharField(null=True, blank=True, max_length=255)

    # Fields that are slightly used, but should be removed.
    phone_caller_id_name = models.CharField(null=True, blank=True, max_length=255)
    phone_type_synced = models.CharField(max_length=3, null=True, blank=True)
    is_followup_cp = models.BooleanField(default=False, null=True)
    has_responded2 = models.BooleanField(default=False, null=True)
    has_responded_dead_auto2 = models.BooleanField(default=False, null=True)
    count_as_unique = models.BooleanField(default=False, null=True)
    unread_user_id_array_raw = models.CharField(null=True, blank=True, max_length=255)
    has_delivered_sms_only = models.BooleanField(default=False, null=True)
    send_sms = models.BooleanField(default=False, null=True)
    sms_status = models.CharField(null=True, blank=True, max_length=255)
    is_associated_dnc = models.BooleanField(default=False, null=True)
    last_message_status = models.CharField(null=True, blank=True, max_length=64)
    last_message_error = models.CharField(null=True, blank=True, max_length=64)
    last_email_sent = models.DateTimeField(null=True, blank=True)
    total_mailings_sent = models.IntegerField(default=0, null=True, blank=True)
    last_outbound_call = models.DateTimeField(null=True, blank=True)
    last_inbound_call = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'sherpa'
        unique_together = ('campaign', 'prospect')
        ordering = ('id',)

    def __str__(self):
        return "%s - %s %s" % (
            self.campaign.name, self.prospect.first_name, self.prospect.last_name)

    @property
    def is_valid_send(self):
        """
        Determine if the campaign prospect can be sent a message and update data about the instance
        if not valid.
        """
        company = self.prospect.company
        if not company:
            self.sms_status = 'no_company'
            self.save(update_fields=['sms_status'])
            return False

        if company.is_messaging_disabled:
            self.sent = False
            self.skipped = True
            self.save(update_fields=['sent', 'skipped'])
            return False

        return True

    @property
    def should_send_carrier_approved_template(self):
        """
        DEPRECATED: Carrier-approved templates should no longer be used, in favor of custom
            templates with required identification and opt out language tags.
        """
        return False

        return all([
            self.campaign.company.send_carrier_approved_templates,
            self.prospect.is_carrier_template_verification_required(),
        ])

    def sms_msg_text(self, sender_name=None, template=None):
        """
        Returns the formatted message that should be sent in bulk sends.
        """
        template = template or self.campaign.sms_template
        is_carrier_approved = False

        if self.should_send_carrier_approved_template:
            self.randomly_select_carrier_approved_template()
            template = self.sms_carrier_approved_template
            is_carrier_approved = True

        if template and template.is_valid:
            self.sms_template = template
            self.save(update_fields=['sms_template'])
            return self.prospect.build_bulk_message(
                template,
                is_carrier_approved,
                sender_name,
                campaign=self.campaign,
            )
        else:
            return ''

    @property
    def public_sms_url(self):
        """
        Url showing the public sms conversation.
        """
        return f'{settings.APP_URL}/public/sms/{self.prospect.token}/{self.campaign.id}/'

    @property
    def absolute_url(self):
        return self.get_absolute_url()

    @property
    def sherpa_url(self):
        return settings.APP_URL + self.get_absolute_url()

    @property
    def public_url(self):
        """
        DEPRECATED: This is a duplicate property, will remove after removing legacy code.
        """
        return self.public_sms_url

    @property
    def phone_display(self):
        """
        Shows a "reader friendly" version of the phone number.
        """
        if not self.phone_raw:
            return ""
        if len(self.phone_raw) == 10:
            return "(%s) %s-%s" % (self.phone_raw[:3], self.phone_raw[3:6], self.phone_raw[6:])
        else:
            return ""

    @property
    def unread_user_id_array(self):
        """
        Return a list of ids for users that have unread messages.
        """
        if self.unread_user_id_array_raw is not None:
            id_list = self.unread_user_id_array_raw.split(",")
        else:
            id_list = 'na'
        return id_list

    @property
    def is_priority(self):
        """
        Indicate if `Prospect` is marked as 'is_priority.
        """
        return self.prospect.is_priority

    @property
    def is_qualified_lead(self):
        """
        Indicate if `Prospect` is marked as 'is_qualified_lead'.
        """
        return self.prospect.is_qualified_lead

    def clone(self, data):
        """
        Clone a campaign prospect to make a new one with updated data.

        :arg data: Dictionary of data to replace for the cloned prospect. The only required field is
                   `phone_raw`. Anything else will update the newly created Prospect record.
        :return CampaignProspect: Return the cloned campaign prospect instance.
        """
        from sherpa.models import PhoneType
        new_phone = clean_phone(data['phone_raw'])
        original_prospect = self.prospect

        # Fields that should be passed in through data, or copied from original.
        copy_fields = ['first_name', 'last_name', 'property_address', 'property_city',
                       'property_state', 'property_zip']

        # Fetch the number data. We are just using the default since that's what we use for lookup.
        carrier = fetch_phonenumber_info(new_phone)
        line_type = carrier['type']
        if line_type != 'mobile':
            raise ValidationError('Can only clone prospects with mobile number.')

        # Update the phone type record.
        PhoneType.objects.update_or_create(
            phone=data.get('phone_raw'),
            defaults={
                'carrier': carrier['name'],
                'type': line_type,
            },
        )

        # Build up the data for the new prospect and then create it..
        new_prospect_kwargs = {
            'phone_raw': new_phone,
            'company': original_prospect.company,
            'phone_type': line_type,
            'cloned_from': self.prospect,
            'sherpa_phone_number_obj': original_prospect.sherpa_phone_number_obj,
        }
        for field in copy_fields:
            new_prospect_kwargs[field] = data.get(field) or getattr(original_prospect, field)
        cloned_prospect = Prospect.objects.create(**new_prospect_kwargs)

        # Remove the fields that aren't on campaign prospect and create the instance.
        remove_fields = [
            'first_name',
            'last_name',
            'cloned_from',
            'sherpa_phone_number_obj',
            'phone_raw',
            'phone_type',
            'company',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
        ]
        for field in remove_fields:
            del new_prospect_kwargs[field]

        cloned_campaign_prospect = CampaignProspect.objects.create(
            prospect=cloned_prospect,
            campaign=self.campaign,
            include_in_skip_trace_cost=False,
            **new_prospect_kwargs,
        )

        return cloned_campaign_prospect

    def transfer(self, new_campaign, reset_skipped=False):
        """
        Reset the data of the campaign prospect.

        This is called when a campaign prospects switches campaigns, generally moved to a follow-up
        campaign.

        :param new_campaign: `Campaign` object that the campaign prospects will be transferred to.
        :param reset_skipped: Boolean that determines if the skipped campaign prospects should have
                              their status reset and be included in the new campaign batch sends.
        """
        self.campaign = new_campaign
        self.sent = False
        self.sms_status = ""
        self.has_responded_via_sms = ""
        self.sms_template = None
        self.send_sms = False
        self.has_delivered_sms_only = False
        self.is_followup_cp = True
        self.phone_type_synced = 'NO'

        if reset_skipped:
            self.skipped = False
            self.skip_reason = ''

        self.save()

    def assign_number(self):
        """
        Assign a valid number to a prospect.
        """
        from sherpa.models import PhoneNumber
        prospect = self.prospect
        market = self.campaign.market

        sherpa_phone_number_object = None

        # Check if the prospect should retain their current sherpa phone number.
        is_twilio_market = market.name == 'Twilio'
        # Only keep the number if we are not moving an existing Prospect with a non twilio number
        # into a Twilio market.
        has_a_phone_and_not_moving_to_twilio_market = prospect.sherpa_phone_number_obj and not(
            prospect.sherpa_phone_number_obj.provider != Provider.TWILIO and is_twilio_market
        )
        has_a_phone_with_valid_status = prospect.sherpa_phone_number_obj and (
            prospect.sherpa_phone_number_obj.status != PhoneNumber.Status.RELEASED
        )
        retain_check = [
            self.campaign.is_followup,
            self.campaign.retain_numbers,
            has_a_phone_and_not_moving_to_twilio_market,
            has_a_phone_with_valid_status,
        ]
        if all(retain_check):
            return prospect.sherpa_phone_number_obj

        # Assign a new sherpa phone number to the prospect.
        if not sherpa_phone_number_object:
            base_phone_qs = market.bulk_phone_numbers

            # Market has no active numbers.
            if not base_phone_qs.exists():
                return None

            phone_number_qs = base_phone_qs.order_by('-created')

            # Get the index number to use to choose the sherpa phone number.
            last_index_assigned = market.last_index_assigned
            index_number = last_index_assigned + 1
            if index_number > len(phone_number_qs) - 1:
                index_number = 0
            market.last_index_assigned = index_number
            market.save(update_fields=['last_index_assigned'])

            sherpa_phone_number_object = phone_number_qs[index_number]
            prospect.sherpa_phone_number_obj = sherpa_phone_number_object
            prospect.save(update_fields=['sherpa_phone_number_obj'])

        return sherpa_phone_number_object

    def update_bulk_sent_stats(self):
        """
        Update various stats after we send a bulk message to a campaign prospect.
        """
        prospect = self.prospect
        campaign = self.campaign
        market = self.campaign.market

        prospect.last_sms_sent_utc = django_tz.now()
        prospect.save(update_fields=['last_sms_sent_utc'])

        # `total_intial_sms_sent_today_count` count used to restrict sends per day.
        market.total_intial_sms_sent_today_count = F('total_intial_sms_sent_today_count') + 1
        market.save(update_fields=['total_intial_sms_sent_today_count'])

        # Update campaign aggregated stats
        stats = campaign.campaign_stats
        stats.total_sms_sent_count = F('total_sms_sent_count') + 1
        stats.save(update_fields=['total_sms_sent_count'])

        stats = campaign.campaign_stats
        stats.total_intial_sms_sent_today_count = F('total_intial_sms_sent_today_count') + 1
        stats.save(update_fields=['total_intial_sms_sent_today_count'])

        self.sms_status = 'sent'
        self.has_delivered_sms_only = True
        return self.save(update_fields=['sms_status', 'has_delivered_sms_only'])

    def set_skip_reason(self, reason):
        self.sent = False
        self.skipped = True
        self.skip_reason = reason
        self.save(update_fields=['sent', 'skipped', 'skip_reason'])

    def check_skip(self, force_skip=False):  # noqa: C901
        """
        Determine if the prospect should be skipped and save the skip reason if so.
        """
        from sherpa.models import LitigatorList, ReceiptSmsDirect
        prospect = self.prospect
        company = prospect.company
        campaign = self.campaign
        prospect_number = prospect.phone_raw
        stats_batch = self.stats_batch

        if force_skip:
            self.set_skip_reason(CampaignProspect.SkipReason.FORCED)
            stats_batch.skipped_force = F('skipped_force') + 1
            stats_batch.save(update_fields=['skipped_force'])
            return True

        if all([
            company.send_carrier_approved_templates,
            prospect.is_carrier_template_verification_required(),
            not company.has_valid_outgoing,
        ]):
            self.set_skip_reason(CampaignProspect.SkipReason.OUTGOING_NOT_SET)
            stats_batch.skipped_outgoing_not_set = F('skipped_outgoing_not_set') + 1
            stats_batch.save(update_fields=['skipped_outgoing_not_set'])
            return True

        # Skip verizon users for non Twilio markets.
        if self.campaign.market.phone_provider == Provider.TELNYX and prospect.is_verizon:
            self.set_skip_reason(CampaignProspect.SkipReason.VERIZON)
            stats_batch.skipped_verizon = F('skipped_verizon') + 1
            stats_batch.save(update_fields=['skipped_verizon'])
            return True

        if prospect.opted_out:
            self.set_skip_reason(CampaignProspect.SkipReason.OPTED_OUT)
            stats_batch.skipped_opted_out = F('skipped_opted_out') + 1
            stats_batch.save(update_fields=['skipped_opted_out'])
            return True

        # IF prospect has responded to a previous message then skip it
        if campaign.skip_prospects_who_messaged and prospect.has_responded_via_sms == 'yes':
            self.set_skip_reason(CampaignProspect.SkipReason.HAS_RESPONDED)
            stats_batch.skipped_has_previous_response = F('skipped_has_previous_response') + 1
            stats_batch.save(update_fields=['skipped_has_previous_response'])
            return True

        # Check if prospect has sent a bulk message in the last interval of days, determined by
        # their `threshold_days` and if yes skip.
        skip_threshold_date = django_tz.now() - timedelta(days=company.threshold_days)
        if not company.threshold_exempt:
            skip_send_count = ReceiptSmsDirect.objects.filter(
                phone_raw=prospect.phone_raw,
                sent_date__gte=skip_threshold_date,
            ).count()
            if skip_send_count > 0:
                self.set_skip_reason(CampaignProspect.SkipReason.THRESHOLD_MESSAGE)
                stats_batch.skipped_msg_threshold_days = F('skipped_msg_threshold_days') + 1
                stats_batch.save(update_fields=['skipped_msg_threshold_days'])
                return True

        if prospect.do_not_call:
            self.set_skip_reason(CampaignProspect.SkipReason.COMPANY_DNC)
            campaign_stats = campaign.campaign_stats
            campaign_stats.total_dnc_count = campaign_stats.total_dnc_count + 1
            campaign_stats.save(update_fields=['total_dnc_count'])
            stats_batch.skipped_internal_dnc = F('skipped_internal_dnc') + 1
            stats_batch.save(update_fields=['skipped_internal_dnc'])
            return True

        if prospect.wrong_number:
            self.set_skip_reason(CampaignProspect.SkipReason.WRONG_NUMBER)
            campaign_stats = campaign.campaign_stats
            campaign_stats.total_wrong_number_count = campaign_stats.total_wrong_number_count + 1
            campaign_stats.save(update_fields=['total_wrong_number_count'])
            stats_batch.skipped_wrong_number = F('skipped_wrong_number') + 1
            stats_batch.save(update_fields=['skipped_wrong_number'])
            return True

        dnc_internal_list = InternalDNC.objects.filter(phone_raw=prospect_number, company=company)
        if len(dnc_internal_list) > 0:
            prospect.do_not_call = True
            prospect.save(update_fields=['do_not_call'])
            self.set_skip_reason(CampaignProspect.SkipReason.PUBLIC_DNC)
            campaign_stats = campaign.campaign_stats
            campaign_stats.total_dnc_count = campaign_stats.total_dnc_count + 1
            campaign_stats.save(update_fields=['total_dnc_count'])

            stats_batch.skipped_internal_dnc = F('skipped_internal_dnc') + 1
            stats_batch.save(update_fields=['skipped_internal_dnc'])

        is_litigator_list = LitigatorList.objects.filter(phone=prospect_number).exists()

        if is_litigator_list:
            prospect.do_not_call = True
            prospect.save(update_fields=['do_not_call'])
            self.set_skip_reason(CampaignProspect.SkipReason.LITIGATOR)
            campaign_stats = campaign.campaign_stats
            campaign_stats.total_dnc_count = campaign_stats.total_dnc_count + 1
            campaign_stats.save(update_fields=['total_dnc_count'])
            stats_batch.skipped_litigator = F('skipped_litigator') + 1
            stats_batch.save(update_fields=['skipped_litigator'])
            return True

        has_sms_direct_receipt = ReceiptSmsDirect.objects.filter(
            phone_raw=prospect_number,
            campaign=campaign,
            company=company,
        ).exists()

        if has_sms_direct_receipt:
            # Recipient has received a message in another campaign.
            self.set_skip_reason(CampaignProspect.SkipReason.SMS_RECEIPT)
            return True

        return False

    def count_prospect(self, is_first_phone, is_new_prospect, is_new_campaign_prospect):
        """
        Determine if we should count the prospect in unique, monthly upload, and skip trace count
        costs.
        """
        from sherpa.models import PhoneType
        update_fields = ['count_as_unique']

        # Mark first record as unique to keep track of number of properties in upload.
        if is_first_phone and is_new_campaign_prospect:
            self.count_as_unique = True

        # If prospect is not new, or property has already been counted to charge, stop here.
        if not is_new_prospect or (self.prospect.prop and self.prospect.prop.is_charged):
            self.save(update_fields=update_fields)
            return

        # Determine if we should count the prospect against monthly upload count.
        phone_data = self.prospect.phone_data

        is_verizon = self.prospect.is_verizon
        is_twilio_int = self.prospect.company.telephonyconnection_set.filter(
            provider=Provider.TWILIO,
        ).exists()

        should_count_monthly_usage = all([
            not is_verizon or is_twilio_int,
            phone_data is None or phone_data and phone_data.type == PhoneType.Type.MOBILE,
        ])
        if should_count_monthly_usage:
            self.include_in_upload_count = True
            update_fields.extend(['include_in_upload_count'])
            self.prospect.company.monthly_upload_count += 1
            self.prospect.company.save(update_fields=['monthly_upload_count'])
            self.include_in_skip_trace_cost = True
            update_fields.extend(['include_in_skip_trace_cost'])

            # Mark Property as charged.
            if self.prospect.prop:
                self.prospect.prop.is_charged = True
                self.prospect.prop.save(update_fields=['is_charged'])

        self.save(update_fields=update_fields)

    def push_to_zapier(self, user):
        """
        Send a prospect to Zapier through their Zapier webhook.

        :param User user: The user that is pushing the prospect to Zapier.
        """
        if not self.campaign.zapier_webhook:
            raise Exception('Campaign prospect {self.id} does not have a Zapier Webhook.')

        prospect = self.prospect
        webhook_url = self.campaign.zapier_webhook.webhook_url

        # Build up an array of notes to send to zapier.
        notes = [note.text for note in prospect.note_set.all()]

        # Send request to the Zapier webhook
        lead_stage_title = prospect.lead_stage.lead_stage_title if prospect.lead_stage else ''
        data = {
            'lead_fullname': f'{prospect.first_name} {prospect.last_name}',
            'lead_first_name': prospect.first_name,
            'lead_last_name': prospect.last_name,
            'lead_email_address': prospect.email,
            'lead_stage': lead_stage_title,
            'campaign_name': self.campaign.name,
            'sherpa_phone_number': prospect.sherpa_phone_number_obj.phone,
            'custom_field': prospect.custom1,
            'custom_field2': prospect.custom2,
            'custom_field3': prospect.custom3,
            'custom_field4': prospect.custom4,
            'property_address_one_line': prospect.address_display,
            'property_street': prospect.property_address,
            'property_city': prospect.property_city,
            'property_state': prospect.property_state,
            'property_zipcode': prospect.property_zip,
            'mailing_street': prospect.mailing_address,
            'mailing_city': prospect.mailing_city,
            'mailing_state': prospect.mailing_state,
            'mailing_zipcode': prospect.mailing_zip,
            'property_phone': prospect.phone_display,
            'sherpa_conversation_link': self.public_sms_url,
            'prospect_link': settings.APP_URL + prospect.get_absolute_url(),
            'notes': notes,
            'agent': prospect.agent.fullname if prospect.agent else '',
        }

        requests.post(webhook_url, json=data)

        # Qualify the lead when we push to Zapier
        qualified_prospect, _ = prospect.toggle_qualified_lead(user, True)
        qualified_prospect.saved_to_zapier_dt = django_tz.now()

        # Set the new lead stage for the prospect
        lead_stage_pushed_to_podio_list = LeadStage.objects.filter(
            is_active=True,
            lead_stage_title='Pushed to Podio',
            company=self.campaign.company,
        )
        if lead_stage_pushed_to_podio_list:
            lead_stage_pushed_to_podio = lead_stage_pushed_to_podio_list[0]
        else:
            lead_stage_pushed_to_podio = None

        if lead_stage_pushed_to_podio is not None:
            qualified_prospect.lead_stage = lead_stage_pushed_to_podio

        return qualified_prospect.save(update_fields=[
            'lead_stage',
            'saved_to_zapier_dt',
        ])

    def send_podio_email(self, user):
        """
        Sends an email to a specified email in the campaign settings. Users can setup a "webhook"
        which will then create the data directly in podio.
        """
        prospect = self.prospect
        podio_push_email = self.campaign.podio_push_email_address

        if not podio_push_email:
            raise Exception(f'Podio push email not setup for campaign {self.campaign.name}.')

        # Prepare the data in the form that the email webhook is expecting.
        first_name_raw = prospect.first_name or ''
        last_name_raw = prospect.last_name or ''
        property_address_raw = prospect.property_address
        property_city_raw = prospect.property_city
        property_state_raw = prospect.property_state
        lead_phone_raw = prospect.phone_display
        sherpa_conversation_link = prospect.public_url

        first_name_raw = first_name_raw.strip() if first_name_raw else ''
        last_name_raw = last_name_raw.strip() if last_name_raw else ''
        property_address_raw = property_address_raw.strip() if property_address_raw else ''
        property_city_raw = property_city_raw.strip() if property_city_raw else ''
        property_state_raw = property_state_raw.strip() if property_state_raw else ''
        lead_phone_raw = lead_phone_raw.strip() if lead_phone_raw else ''

        first_name = first_name_raw.replace(' ', '_')
        last_name = last_name_raw.replace(' ', '_')
        property_address = property_address_raw.replace(' ', '_')
        property_city = property_city_raw.replace(' ', '_')
        property_state = property_state_raw.replace(' ', '_')
        lead_phone = lead_phone_raw.replace(' ', '_')

        # This is the final format of data that is needed of the podio email.
        sherpa_prospect_info = '%s_%s %s %s_%s_%s_%s %s' % (
            first_name,
            last_name,
            lead_phone,
            property_address,
            property_city,
            property_state, prospect.property_zip,
            sherpa_conversation_link,
        )

        # Setup & Send Email
        text_content = sherpa_prospect_info
        html_content = render_to_string(
            'email/email_push_to_podio.html',
            {'sherpa_prospect_info': sherpa_prospect_info},
        )
        email = EmailMultiAlternatives(
            'Sherpa Lead',
            text_content,
            settings.DEFAULT_FROM_EMAIL,
            [podio_push_email],
        )
        email.attach_alternative(html_content, "text/html")
        email.send()

        # Update the prospect to be qualified.
        qualified_prospect, _ = prospect.toggle_qualified_lead(user, True)
        qualified_prospect.emailed_lead_to_podio_dt = django_tz.now()

        # Update the lead stage to show that the prospect has been pushed to podio.
        lead_stage_pushed_to_podio_list = LeadStage.objects.filter(
            is_active=True,
            lead_stage_title='Pushed to Podio',
            company=self.campaign.company,
        )
        if lead_stage_pushed_to_podio_list:
            lead_stage_pushed_to_podio = lead_stage_pushed_to_podio_list[0]
        else:
            lead_stage_pushed_to_podio = None

        if lead_stage_pushed_to_podio:
            qualified_prospect.lead_stage = lead_stage_pushed_to_podio

        qualified_prospect.save(update_fields=[
            'lead_stage',
            'emailed_lead_to_podio_dt',
        ])

    def randomly_select_carrier_approved_template(self):
        """
        Randomly selects a new carrier-approved template.
        """
        from sms.models import CarrierApprovedTemplate
        self.sms_carrier_approved_template = CarrierApprovedTemplate.objects.random(
            company=self.prospect.company)
        self.save(update_fields=['sms_carrier_approved_template'])

    def mark_as_viewed(self, user, value):
        """
        Updates instances `has_been_viewed` to the value provided.

        User is added for convenience.
        """
        self.has_been_viewed = value
        self.save(update_fields=['has_been_viewed'])

    def save(self, *args, **kwargs):  # noqa: C901
        from campaigns.models import CampaignAggregatedStats
        from sherpa.models import StatsBatch

        if self.pk is not None and self.prospect.phone_type == 'mobile':
            # Update aggregated fields for mobile campaign prospects.
            f_sent_skipped_change = 0
            kwargs['update_fields'] = kwargs.get('update_fields', None)

            for field in ['sent', 'skipped']:
                if all([
                        kwargs['update_fields'] is None or field in kwargs['update_fields'],
                        self.tracker.has_changed(field),
                ]):
                    f_sent_skipped_change += 1 if getattr(self, field) else -1

            if f_sent_skipped_change:
                campaign = Campaign.objects.get(id=self.campaign_id)
                new_sent_skipped = F('total_initial_sent_skipped') + f_sent_skipped_change
                campaign.campaign_stats.total_initial_sent_skipped = new_sent_skipped
                campaign.campaign_stats.save(update_fields=['total_initial_sent_skipped'])

        if self.prospect.phone_type and self.phone_type_synced != 'YES':
            # Update the aggregated fields for phone type.
            if self.prospect.phone_type == 'mobile':
                self.phone_type_synced = 'YES'
                f_total_mobile = F('total_mobile')
                f_total_mobile = f_total_mobile + 1
                stats_id = self.campaign.campaign_stats.id
                CampaignAggregatedStats.objects.filter(id=stats_id).update(
                    total_mobile=f_total_mobile)
            elif self.prospect.phone_type == 'landline':
                self.phone_type_synced = 'YES'
                f_total_landline = F('total_landline')
                f_total_landline = f_total_landline + 1
                stats_id = self.campaign.campaign_stats.id
                CampaignAggregatedStats.objects.filter(id=stats_id).update(
                    total_landline=f_total_landline)
            else:
                self.phone_type_synced = 'YES'
                f_total_other = F('total_phone_other')
                f_total_other = f_total_other + 1
                stats_id = self.campaign.campaign_stats.id
                CampaignAggregatedStats.objects.filter(id=stats_id).update(
                    total_phone_other=f_total_other)

        try:
            if self.stats_batch:
                stats_batch_update = {}

                # Update the stats batch aggregated fields.
                kwargs['update_fields'] = kwargs.get('update_fields', None)
                if all([
                    kwargs['update_fields'] is None or 'has_responded2' in kwargs['update_fields'],
                    self.tracker.has_changed('has_responded2'),
                ]):
                    if self.has_responded2:
                        stats_batch_update["received"] = F('received') + 1

                kwargs['update_fields'] = kwargs.get('update_fields', None)
                if all([
                    kwargs['update_fields'] is None or 'has_responded_dead_auto2' in kwargs['update_fields'],  # noqa: E501
                    self.tracker.has_changed('has_responded_dead_auto2'),
                ]):
                    if self.has_responded_dead_auto2:
                        stats_batch_update["received_dead_auto"] = F('received_dead_auto') + 1

                if stats_batch_update:
                    StatsBatch.objects.filter(id=self.stats_batch_id).update(**stats_batch_update)
        except StatsBatch.DoesNotExist:
            # During loaddata the stats batch does not exist yet.
            pass

        if self.tracker.has_changed('last_inbound_call') or self.tracker.has_changed('last_outbound_call'):  # noqa: E501
            self.prospect.update_propstack_listing()

        return super(CampaignProspect, self).save(*args, **kwargs)


class LeadStage(SortOrderModelMixin, models.Model):
    """
    Companies track their prospects through various stages.

    There are some stages that are needed for the system, for example when a message is received it
    moves the prospect into "Response Received" stage. There are other stages that are created on
    just a company level.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    is_custom = models.BooleanField(default=False)
    lead_stage_title = models.CharField(max_length=32, db_index=True)
    sort_order = models.IntegerField(default=0)
    description = models.CharField(blank=True, max_length=64)

    class Meta:
        app_label = 'sherpa'
        ordering = ('sort_order',)

        # This will prevent admins from duplicating titles.
        unique_together = (
            ('company', 'lead_stage_title'),
        )

    def __str__(self):
        return self.lead_stage_title

    def get_sortable_queryset(self):
        """
        Returns the queryset of sortable instances.
        """
        return self.company.leadstage_set.all()


class CampaignAccess(models.Model):
    """
    Grouping between a Campaign and UserProfile. By default all users of a company have access to a
    Campaign unless changed Admin.
    """
    campaign = models.ForeignKey('Campaign', on_delete=models.CASCADE)
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'sherpa'
        unique_together = ('campaign', 'user_profile')
        verbose_name_plural = 'campaign access'


class InternalDNC(models.Model):
    """
    Individual company's do not call list.
    """
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    added_datetime = models.DateTimeField(auto_now_add=True)
    phone_raw = models.CharField(null=True, blank=True, max_length=16, db_index=True)

    class Meta:
        app_label = 'sherpa'


class Activity(models.Model):
    """
    Activity of a campaign prospect.
    """
    class Title:
        ADDED_DNC = 'Added to DNC'
        REMOVED_DNC = 'Removed from DNC'
        OWNER_NOT_VALID = 'Owner Not Valid'
        OWNER_VERIFIED = 'Owner Verified'
        OWNER_UNVERIFIED = 'Owner Unverified'
        ADDED_PRIORITY = 'Added as Priority'
        REMOVED_PRIORITY = 'Removed as Priority'
        ADDED_QUALIFIED = 'Qualified Lead Added'
        REMOVED_QUALIFIED = 'Qualified Lead Removed'
        ADDED_AUTODEAD = 'Added Autodead'
        REMOVED_AUTODEAD = 'Removed Autodead'
        CREATED_NOTE = 'Created Note'
        ADDED_WRONG = 'Added Wrong Number'
        REMOVED_WRONG = 'Removed Wrong Number'
        CLICK_TO_CALL = 'Click to Call'
        INBOUND_CALL = 'Inbound Call'
        OUTBOUND_CALL = 'Outbound Call'
        GENERAL_CALL = 'General Call'

        CHOICES = (
            (ADDED_DNC, ADDED_DNC),
            (REMOVED_DNC, REMOVED_DNC),
            (OWNER_NOT_VALID, OWNER_NOT_VALID),
            (OWNER_VERIFIED, OWNER_VERIFIED),
            (OWNER_UNVERIFIED, OWNER_UNVERIFIED),
            (ADDED_PRIORITY, ADDED_PRIORITY),
            (REMOVED_PRIORITY, REMOVED_PRIORITY),
            (ADDED_QUALIFIED, ADDED_QUALIFIED),
            (REMOVED_QUALIFIED, REMOVED_QUALIFIED),
            (ADDED_AUTODEAD, ADDED_AUTODEAD),
            (REMOVED_AUTODEAD, REMOVED_AUTODEAD),
            (CREATED_NOTE, CREATED_NOTE),
            (ADDED_WRONG, ADDED_WRONG),
            (REMOVED_WRONG, REMOVED_WRONG),
            (CLICK_TO_CALL, CLICK_TO_CALL),
            (INBOUND_CALL, INBOUND_CALL),
            (OUTBOUND_CALL, OUTBOUND_CALL),
            (GENERAL_CALL, GENERAL_CALL),
        )

    prospect = models.ForeignKey(Prospect, null=True, blank=True, on_delete=models.CASCADE)
    date_utc = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=255, choices=Title.CHOICES, db_index=True)
    description = models.CharField(max_length=255)
    related_lookup = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    # Not used, can be removed.
    icon = models.CharField(max_length=255)

    class Meta:
        app_label = 'sherpa'
        verbose_name_plural = 'activities'
        ordering = ('-date_utc',)


class Note(AbstractNote):
    """
    Notes are displayed on the prospect page.
    """
    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, null=True)

    def __str__(self):
        return self.text[:30]

    class Meta(AbstractNote.Meta):
        app_label = 'sherpa'


class UploadProspects(UploadBaseModel):
    """
    Created per Prospect Upload. Displays/tracks progress and status of upload
    """
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.CASCADE)
    transaction = models.ForeignKey(
        'billing.Transaction', null=True, blank=True, on_delete=models.CASCADE)
    upload_start = models.DateTimeField(null=True, blank=True)
    upload_end = models.DateTimeField(null=True, blank=True)
    properties_imported = models.IntegerField(default=0)
    prospects_imported = models.IntegerField(default=0)
    new = models.IntegerField(default=0)
    existing = models.IntegerField(default=0)
    new_properties = models.IntegerField(default=0)
    existing_properties = models.IntegerField(default=0)
    has_header_row = models.BooleanField(default=True)

    # Amount of prospects that count against the monthly upload limit.
    exceeds_count = models.PositiveIntegerField(null=True, blank=True)

    total_properties = models.IntegerField(default=0)
    # total_prospects can be delete with old upload code
    total_prospects = models.IntegerField(default=0)
    duplicated_prospects = models.IntegerField(default=0)
    total_mobile_numbers = models.IntegerField(default=0)
    total_landline_numbers = models.IntegerField(default=0)
    total_other_numbers = models.IntegerField(default=0)
    total_internal_dnc = models.IntegerField(default=0)
    total_associated_internal_dnc = models.IntegerField(default=0)
    total_litigator_list = models.IntegerField(default=0)
    total_associated_litigator_list = models.IntegerField(default=0)

    has_skip_trace = models.BooleanField(default=False)
    email_confirmation_sent = models.BooleanField(default=False)
    additional_upload_cost_amount = models.DecimalField(default=0, max_digits=6, decimal_places=2)
    upload_error = models.TextField(null=True, blank=True)

    # Mapping fields.
    field_a = models.CharField(null=True, blank=True, max_length=20)
    field_b = models.CharField(null=True, blank=True, max_length=20)
    field_c = models.CharField(null=True, blank=True, max_length=20)
    field_d = models.CharField(null=True, blank=True, max_length=20)
    field_e = models.CharField(null=True, blank=True, max_length=20)
    field_f = models.CharField(null=True, blank=True, max_length=20)
    field_g = models.CharField(null=True, blank=True, max_length=20)
    field_h = models.CharField(null=True, blank=True, max_length=20)
    field_i = models.CharField(null=True, blank=True, max_length=20)
    field_j = models.CharField(null=True, blank=True, max_length=20)
    field_k = models.CharField(null=True, blank=True, max_length=20)
    field_l = models.CharField(null=True, blank=True, max_length=20)
    fullname_column_number = models.IntegerField(null=True, blank=True)
    first_name_column_number = models.IntegerField(null=True, blank=True)
    last_name_column_number = models.IntegerField(null=True, blank=True)
    email_column_number = models.IntegerField(null=True, blank=True)
    custom_1_column_number = models.IntegerField(null=True, blank=True)
    custom_2_column_number = models.IntegerField(null=True, blank=True)
    custom_3_column_number = models.IntegerField(null=True, blank=True)
    custom_4_column_number = models.IntegerField(null=True, blank=True)
    phone_1_number = models.IntegerField(null=True, blank=True)
    phone_2_number = models.IntegerField(null=True, blank=True)
    phone_3_number = models.IntegerField(null=True, blank=True)
    phone_4_number = models.IntegerField(null=True, blank=True)
    phone_5_number = models.IntegerField(null=True, blank=True)
    phone_6_number = models.IntegerField(null=True, blank=True)
    phone_7_number = models.IntegerField(null=True, blank=True)
    phone_8_number = models.IntegerField(null=True, blank=True)
    phone_9_number = models.IntegerField(null=True, blank=True)
    phone_10_number = models.IntegerField(null=True, blank=True)
    phone_11_number = models.IntegerField(null=True, blank=True)
    phone_12_number = models.IntegerField(null=True, blank=True)

    # Address fields.
    street_column_number = models.IntegerField(null=True, blank=True)
    city_column_number = models.IntegerField(null=True, blank=True)
    state_column_number = models.IntegerField(null=True, blank=True)
    zipcode_column_number = models.IntegerField(null=True, blank=True)
    mailing_street_column_number = models.IntegerField(null=True, blank=True)
    mailing_city_column_number = models.IntegerField(null=True, blank=True)
    mailing_state_column_number = models.IntegerField(null=True, blank=True)
    mailing_zipcode_column_number = models.IntegerField(null=True, blank=True)

    class Meta:
        app_label = 'sherpa'
        verbose_name_plural = 'upload prospects'

    @property
    def upload_time(self):
        if self.upload_start and self.upload_end:
            start = self.upload_start
            end = self.upload_end
            diff = end - start
            minutes = diff.seconds / 60
            return minutes
        else:
            return 0

    @property
    def percent_complete(self):
        if self.total_rows == 0:
            return '100%'
        return f'{int((float(self.last_row_processed) / float(self.total_rows)) * 100)}%'

    @property
    def prospects_imported_calculated(self):
        return CampaignProspect.objects.filter(Q(upload_prospects=self)).count()

    @property
    def properties_imported_calculated(self):
        return CampaignProspect.objects.filter(
            Q(upload_prospects=self), Q(include_in_upload_count=True),
        ).count()

    @property
    def total_litigators(self):
        return CampaignProspect.objects.filter(
            Q(upload_prospects=self),
            Q(is_associated_litigator=True) | Q(is_litigator=True),
        ).count()

    @property
    def total_internal_dnc2(self):
        return CampaignProspect.objects.filter(
            Q(is_associated_dnc=True) | Q(prospect__do_not_call=True),
            upload_prospects=self,
        ).count()

    @property
    def unique_property_tags(self):
        total_properties = self.property_set.count()
        tags_applied = self.property_set.filter(
            tags__isnull=False,
        ).values(
            'tags__id',
        ).order_by(
            'tags__id',
        ).annotate(
            tag_count=Count('tags__id'),
        ).distinct()
        return sum([tag['tag_count'] == total_properties for tag in tags_applied])

    @property
    def total_phone_lookups_remaining(self):
        return CampaignProspect.objects.filter(Q(upload_prospects=self), Q(phone_type=None)).count()

    @property
    def total_mobile_phones(self):
        return self.campaignprospect_set.filter(prospect__phone_type='mobile').count()

    @property
    def total_landline_phones(self):
        return self.campaignprospect_set.filter(prospect__phone_type='landline').count()

    @property
    def total_other_phones(self):
        return self.campaignprospect_set.exclude(
            prospect__phone_type__in=[None, 'mobile', 'landline'],
        ).count()

    @property
    def has_phone_column(self):
        if any([
                self.field_a == 'phone',
                self.field_b == 'phone',
                self.field_c == 'phone',
                self.field_d == 'phone',
                self.field_e == 'phone',
                self.field_f == 'phone',
                self.field_g == 'phone',
                self.field_h == 'phone',
                self.field_i == 'phone',
        ]):
            return True
        else:
            return False

    def update_upload_stats(self, prospect, is_new_prospect):
        """
        Update `Prospect` related stats.

        :param prospect: `Prospect` object we're counting.
        :param is_new_prospect: Boolean to indicate if `Prospect` is new.
        """
        update_fields = []

        if is_new_prospect:
            self.new = F('new') + 1
            update_fields.append('new')
        else:
            self.existing = F('existing') + 1
            update_fields.append('existing')

        self.prospects_imported = F('prospects_imported') + 1
        update_fields.append('prospects_imported')

        # Increment phone count here on Upload Prospects
        if prospect.phone_type == Prospect.PhoneType.MOBILE:
            self.total_mobile_numbers = F('total_mobile_numbers') + 1
            update_fields.append('total_mobile_numbers')
        elif prospect.phone_type == Prospect.PhoneType.LANDLINE:
            self.total_landline_numbers = F('total_landline_numbers') + 1
            update_fields.append('total_landline_numbers')
        else:
            self.total_other_numbers = F('total_other_numbers') + 1
            update_fields.append('total_other_numbers')

        self.save(update_fields=update_fields)

    def charge(self):
        """
        Calculate charge for upload.
        """

        # If we have remaining uploads, or don't have a valid authorized transaction that
        # hasn't already been charged, then don't charge.
        if any([
            self.company.upload_count_remaining_current_billing_month,
            not self.transaction or any([
                not self.transaction.is_authorized,
                self.transaction.is_failed,
                self.transaction.is_charged,
            ]),
        ]):
            return

        # Calculate number of records in this upload are new records and need
        # to be charged for. Filter out records that were from a previous upload.
        max_charge_count = CampaignProspect.objects.annotate(
            num_uploads=Count('upload_prospects'),
        ).filter(
            upload_prospects=self,
            include_in_upload_count=True,
        ).exclude(num_uploads__gt=1).count()

        total_free = self.total_rows - self.exceeds_count
        charge_count = max_charge_count - total_free

        cost_per_upload = self.company.cost_per_upload
        calculated_amount = charge_count * cost_per_upload

        # If there's nothing to charge, then don't charge.
        if calculated_amount <= 0:
            return

        self.transaction.charge(calculated_amount)

    def restart(self):
        from prospects.tasks import upload_prospects_task2
        self.status = self.Status.AUTO_STOP
        self.stop_upload = False
        self.save(update_fields=['status', 'stop_upload'])

        upload_prospects_task2.delay(self.id)

    @staticmethod
    def create_new(user, total_rows, filename, campaign, path=None, duplicated_prospects=0):
        """
        Create new `UploadProspects` object
        """
        if not path:
            path = f'{uuid.uuid4()}.csv'

        upload_prospects = UploadProspects.objects.create(
            path=path,
            campaign=campaign,
            created_by=user,
            company=user.profile.company,
            uploaded_filename=filename,
            total_rows=total_rows,
            duplicated_prospects=duplicated_prospects,
        )

        upload_prospects.save()

        return upload_prospects


class ZapierWebhook(models.Model):
    """
    Connects a Company with a Zapier webhook.
    """
    class Status:
        ACTIVE = 'active'
        INACTIVE = 'inactive'

        CHOICES = (
            (ACTIVE, 'Active'),
            (INACTIVE, 'Inctive'),
        )

    class Type:
        PROSPECT = 'prospect'
        SMS = 'sms'

        CHOICES = (
            (PROSPECT, 'Prospect'),
            (SMS, 'SMS'),
        )

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='webhooks')

    created = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, default=Status.ACTIVE, choices=Status.CHOICES)
    name = models.CharField(max_length=255)
    webhook_url = models.CharField(max_length=255)
    webhook_type = models.CharField(max_length=16, default=Type.PROSPECT, choices=Type.CHOICES)

    class Meta:
        app_label = 'sherpa'
        ordering = ('id',)

    def __str__(self):
        return f"{self.name} - {self.company} - {self.status}"

    def save(self, *args, **kwargs):
        """
        When saving a webhook to inactive, we want to remove that webhook from all campaigns.
        """
        if self.id:
            current = ZapierWebhook.objects.get(id=self.id)
            if all([
                current.status == ZapierWebhook.Status.ACTIVE,
                self.status == ZapierWebhook.Status.INACTIVE,
            ]):
                self.remove_from_campaigns()

        super(ZapierWebhook, self).save(*args, **kwargs)

    def remove_from_campaigns(self):
        """
        Remove this webhook from all campaigns that it's currently saved to.
        """
        queryset = self.campaign_set.filter(zapier_webhook=self)
        queryset.update(zapier_webhook=None)

    @property
    def is_default(self):
        return self.company.default_zapier_webhook_id == self.pk


class UploadInternalDNC(UploadBaseModel):
    """
    The Do Not Call list per company.

    Companies can add a number to their DNC list via the prospect page.
    """
    total_phone_numbers_saved = models.IntegerField(default=0)
    has_column_header = models.BooleanField(default=False)

    class Meta:
        app_label = 'sherpa'


class AreaCodeState(models.Model):
    """
    Top-level market data.

    Companies can have a presense in markets, and that top-level market data is stored in this
    model.
    """
    parent_market = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    area_code = models.CharField(null=True, blank=True, max_length=16)

    # TODO: (aww20190824) city and state are both required.
    state = models.CharField(null=True, blank=True, max_length=16)
    city = models.CharField(null=True, blank=True, max_length=64)
    overlay_group = models.CharField(null=True, blank=True, max_length=64)
    temp_first_choice = models.IntegerField(default=0)
    temp_second_choice = models.IntegerField(default=0)
    latitude = models.CharField(null=True, blank=True, max_length=64)
    longitude = models.CharField(null=True, blank=True, max_length=64)
    market_cap = models.IntegerField(default=15)

    def __str__(self):
        return "{} - {}".format(self.city, self.state)

    class Meta:
        app_label = 'sherpa'
        ordering = ('state', 'city')

    @property
    def market_count(self):
        return Market.objects.filter(parent_market=self, is_active=True).count()

    @property
    def is_open(self):
        """
        Determines if the market is accepting new users to enter.
        """
        return self.market_cap > self.market_count

    @property
    def status(self):
        """
        If markets have an `open` status then new companies may enter that market.

        DEPRECATED: (AWW20190814) Should use the `is_open` bool value instead.
        """
        return 'open' if self.market_cap > self.market_count else 'closed'

    @property  # noqa: F811
    def is_open(self):
        """
        Determine if the market is open for new companies to join.
        """
        return self.market_cap > self.market_count

    @property
    def total_seven_day_skipped_last_thirty_days(self):
        from sherpa.models import StatsBatch
        thirty_days_ago = django_tz.now() - timedelta(days=30)
        sum_dict = StatsBatch.objects.filter(
            parent_market=self,
            created_utc__gte=thirty_days_ago,
        ).aggregate(
            Sum('skipped_msg_threshold_days'),
        )
        sum_seven_day_skipped = sum_dict.get("skipped_msg_threshold_days__sum", 0)

        return sum_seven_day_skipped or 0

    @property
    def total_send_attempts_thirty_days(self):
        from sherpa.models import StatsBatch
        thirty_days_ago = django_tz.now() - timedelta(days=30)
        sum_dict = StatsBatch.objects.filter(
            parent_market=self,
            created_utc__gte=thirty_days_ago,
        ).aggregate(
            Sum('send_attempt'),
        )
        sum_send_attempt = sum_dict.get("send_attempt__sum", 0)

        return sum_send_attempt or 0

    @property
    def percent_skipped(self):
        if all([
                self.total_seven_day_skipped_last_thirty_days > 0,
                self.total_send_attempts_thirty_days > 0,
        ]):
            percent_skipped = float(self.total_seven_day_skipped_last_thirty_days) / \
                float(self.total_send_attempts_thirty_days) * 100
        else:
            percent_skipped = ''

        return percent_skipped


class SherpaTask(models.Model):
    """
    Controls the flow of sherpa tasks.
    """
    class Status:
        OPEN = 1
        QUEUED = 2
        RUNNING = 3
        COMPLETE = 4
        PAUSED = 5
        ERROR = 6

        CHOICES = (
            (OPEN, 'Open'),
            (QUEUED, 'Queued'),
            (RUNNING, 'Running'),
            (ERROR, 'Error'),
            (PAUSED, 'Paused'),
            (COMPLETE, 'Complete'),
        )

    class Task:
        PUSH_TO_CAMPAIGN = 0
        PUSH_TO_PODIO_CRM = 1
        CHOICES = (
            (PUSH_TO_CAMPAIGN, 'Push to Campaign'),
            (PUSH_TO_PODIO_CRM, 'Push to Podio'),
        )

        TASKS = (
            {
                'send_confirm_email': True,
                'import_path': 'search.tasks.push_to_campaign_task',
                'subject': 'Push to Campaign Completed',
                'template': 'email/email_prospect_hub_push_to_campaign_complete.html',
            },
            {
                'send_confirm_email': False,
                'import_path': 'companies.tasks.push_data_to_podio',
            },
        )

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True, blank=True)
    started = models.DateTimeField(null=True, blank=True)
    completed = models.DateTimeField(null=True, blank=True)

    # Task details
    task = models.PositiveSmallIntegerField(choices=Task.CHOICES)
    attributes = JSONField(encoder=DjangoJSONEncoder)
    metrics = JSONField(encoder=DjangoJSONEncoder, default=dict)
    error_msg = models.TextField(null=True, blank=True)
    delay = models.PositiveIntegerField(default=0)

    # Settings
    status = models.PositiveSmallIntegerField(choices=Status.CHOICES, default=Status.OPEN)
    pause = models.BooleanField(default=False, help_text='Set to True to pause the task.')
    attempts = models.PositiveIntegerField(
        default=0, help_text='Total amount of times a task has been restarted from an error.')

    class Meta:
        app_label = 'sherpa'

    @django_transaction.atomic
    def queue_task(self):
        """
        Queues the task based on the `task` choice by sending it to celery.
        """
        if self.status != self.Status.OPEN:
            return False
        self.status = self.Status.QUEUED
        self.save(update_fields=['status'])

        # Get the relative import path from task display and execute the celery task.
        task_details = self.Task.TASKS[self.task]
        path, func_name = task_details['import_path'].rsplit('.', 1)
        func = getattr(import_module(path), func_name)
        func.apply_async(args=[self.pk], countdown=self.delay)
        return True

    @django_transaction.atomic
    def start_task(self):
        """
        Starts the task if the task is currently queued.
        """
        if self.status != self.Status.QUEUED:
            return False
        self.status = self.Status.RUNNING
        self.started = F('started') or django_tz.now()
        self.save(update_fields=['status', 'started'])
        return True

    @django_transaction.atomic
    def pause_task(self):
        """
        Pauses the task if the task is currently running or in queue
        """
        if self.status not in [self.Status.RUNNING, self.Status.QUEUED]:
            return False
        self.pause = True
        self.status = self.Status.PAUSED
        self.save(update_fields=['pause', 'status'])
        return True

    @django_transaction.atomic
    def restart_task(self):
        """
        Restarts the task if the task has been paused or errored.  If the task is restarting from an
        error, increment an attempt counter.  Do not allow a task to run if attempts is greater than
        two.
        """
        self.refresh_from_db()
        if self.status not in [self.Status.ERROR, self.Status.PAUSED]:
            return False
        if self.attempts > 2:
            return False
        self.pause = False
        self.status = self.Status.OPEN
        self.save(update_fields=['pause', 'status'])
        return self.queue_task()

    @django_transaction.atomic
    def complete_task(self, metrics=None):
        """
        Completes the task if the task is currently running.
        """
        if self.status != self.Status.RUNNING:
            return False
        self.metrics = metrics or self.metrics
        self.status = self.Status.COMPLETE
        self.completed = django_tz.now()
        self.save(update_fields=['metrics', 'status', 'completed'])

        # Send confirmation email.
        task_details = self.Task.TASKS[self.task]
        if not task_details['send_confirm_email']:
            return True

        from ..tasks import sherpa_send_email
        context = {}
        context.update(self.metrics)
        context['name'] = self.created_by.get_full_name()
        context['campaign_id'] = self.attributes['campaign_id']
        context['campaign_name'] = self.attributes['campaign_name']
        context['site_id'] = settings.DJOSER_SITE_ID
        sherpa_send_email.delay(
            task_details['subject'],
            task_details['template'],
            self.created_by.email,
            context,
        )
        return True

    @django_transaction.atomic
    def set_error(self, error_msg=''):
        """
        Sets the task in error preventing it from running until attempting to restart.
        """
        if self.status != self.Status.RUNNING:
            return False
        self.status = self.Status.ERROR
        self.pause = True
        self.attempts = F('attempts') + 1
        self.error_msg = error_msg
        self.save(update_fields=['status', 'pause', 'attempts', 'error_msg'])
        return True
