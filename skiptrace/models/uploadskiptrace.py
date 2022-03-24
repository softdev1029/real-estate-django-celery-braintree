from decimal import Decimal
import uuid

from django.conf import settings
from django.utils import timezone as django_tz

from companies.models import UploadBaseModel
from core import models
from sherpa.utils import (
    get_upload_additional_cost,
)


class UploadSkipTracePropertyTag(models.Model):
    """
    A PropertyTag assigned to an UploadSkipTrace to be applied to each yielded SkipTraceProperty.
    """
    upload_skip_trace = models.ForeignKey(to='sherpa.UploadSkipTrace', on_delete=models.CASCADE)
    property_tag = models.ForeignKey(to='properties.PropertyTag', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('upload_skip_trace', 'property_tag')

    def __str__(self):
        return f'{self.property_tag.name} on {self.upload_skip_trace}'


class UploadSkipTrace(UploadBaseModel):
    """
    Used to track the status of a Skip Trace upload.
    """
    class PushToCampaignStatus:
        OPEN = 'open'
        QUEUED = 'queued'
        RUNNING = 'running'
        ERROR = 'error'
        COMPLETE = 'complete'
        PAUSED = 'paused'
        AUTO_STOP = 'auto_stop'

        CHOICES = (
            (OPEN, 'Open'),
            (QUEUED, 'Queued'),
            (RUNNING, 'Running'),
            (ERROR, 'Error'),
            (AUTO_STOP, 'Stopped'),
            (COMPLETE, 'Complete'),
            (PAUSED, 'Paused'),
        )

    class PushToCampaignStages:
        INITIAL = 'initial'
        CREATING_PROPERTIES = 'creating_properties'
        PUSHING_TO_CAMPAIGN = 'pushing_to_campaign'

        CHOICES = (
            (INITIAL, 'Starting'),
            (CREATING_PROPERTIES, 'Creating properties'),
            (PUSHING_TO_CAMPAIGN, 'Pushing to campaign'),
        )

    property_tags = models.ManyToManyField(
        to='properties.PropertyTag',
        through=UploadSkipTracePropertyTag,
        blank=True,
    )

    transaction = models.ForeignKey(
        'billing.Transaction', null=True, blank=True, on_delete=models.CASCADE)
    push_to_campaign_transaction = models.ForeignKey(
        'billing.Transaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='push_to_campaign_transactions',
    )

    single_upload_authorized = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    is_single_upload = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    upload_start = models.DateTimeField(null=True, blank=True)
    upload_end = models.DateTimeField(null=True, blank=True)
    invitation_code = models.CharField(null=True, blank=True, max_length=64)
    email_confirmation_sent = models.BooleanField(default=False)
    token = models.CharField(null=True, blank=True, max_length=255)
    has_header_row = models.BooleanField(default=True)
    last_idi_token_reset = models.DateTimeField(null=True, blank=True)
    idi_token = models.TextField(null=True, blank=True)

    # Push to campaign fields.
    push_to_campaign_start = models.DateTimeField(null=True, blank=True)
    push_to_campaign_end = models.DateTimeField(null=True, blank=True)
    push_to_campaign_status = models.CharField(
        default=PushToCampaignStatus.OPEN,
        max_length=255,
        choices=PushToCampaignStatus.CHOICES,
    )
    push_to_campaign_stage = models.CharField(
        null=True,
        max_length=255,
        choices=PushToCampaignStages.CHOICES,
        blank=True,
    )
    total_rows_push_to_campaign = models.IntegerField(default=0)
    last_row_push_to_campaign = models.IntegerField(default=0)
    stop_push_to_campaign = models.BooleanField(default=False)
    push_to_campaign_campaign_name = models.CharField(null=True, blank=True, max_length=255)
    push_to_campaign_campaign_id = models.CharField(default="0", max_length=16)
    push_to_campaign_import_type = models.CharField(null=True, blank=True, max_length=16)
    push_to_campaign_email_confirmation_sent = models.BooleanField(default=False)
    push_to_campaign_mobile_phone_count = models.IntegerField(default=0)
    push_to_campaign_landline_phone_count = models.IntegerField(default=0)
    push_to_campaign_other_phone_count = models.IntegerField(default=0)
    push_to_campaign_dnc_count = models.IntegerField(default=0)
    push_to_campaign_litigator_count = models.IntegerField(default=0)

    total_internal_hits = models.IntegerField(default=0)
    total_existing_matches = models.IntegerField(default=0)
    total_hits = models.IntegerField(default=0)
    total_billable_hits = models.IntegerField(default=0)
    total_phone = models.IntegerField(default=0)
    total_email = models.IntegerField(default=0)
    total_addresses = models.IntegerField(default=0)

    # Need to make null/blank to allow for the python2 instances to create record. This should be
    # removed after all instances are on python3.
    total_litigators = models.IntegerField(default=0, null=True, blank=True)

    fullname_column_number = models.IntegerField(null=True, blank=True)
    first_name_column_number = models.IntegerField(null=True, blank=True)
    last_name_column_number = models.IntegerField(null=True, blank=True)
    mailing_street_column_number = models.IntegerField(null=True, blank=True)
    mailing_city_column_number = models.IntegerField(null=True, blank=True)
    mailing_state_column_number = models.IntegerField(null=True, blank=True)
    mailing_zipcode_column_number = models.IntegerField(null=True, blank=True)
    property_street_column_number = models.IntegerField(null=True, blank=True)
    property_city_column_number = models.IntegerField(null=True, blank=True)
    property_state_column_number = models.IntegerField(null=True, blank=True)
    property_zipcode_column_number = models.IntegerField(null=True, blank=True)

    custom_1_column_number = models.IntegerField(null=True, blank=True)
    custom_2_column_number = models.IntegerField(null=True, blank=True)
    custom_3_column_number = models.IntegerField(null=True, blank=True)
    custom_4_column_number = models.IntegerField(null=True, blank=True)
    custom_5_column_number = models.IntegerField(null=True, blank=True)
    custom_6_column_number = models.IntegerField(null=True, blank=True)

    suppress_against_database = models.BooleanField(default=True)
    upload_error = models.TextField(null=True, blank=True)

    # Prop Stack
    is_prop_stack_upload = models.NullBooleanField(default=False)
    prop_stack_file_ready = models.NullBooleanField(default=False)
    begin_prop_stack_processing = models.NullBooleanField(default=False)

    class Meta:
        app_label = "sherpa"
        ordering = ('-id',)

    @staticmethod
    def create_new(user, total_rows, filename=None, path=None, has_header=True):
        """
        Create new UploadSkipTrace object
        """
        if filename and not path:
            path = f'{uuid.uuid4()}.csv'

        upload_skip_trace = UploadSkipTrace.objects.create(
            created_by=user,
            company=user.profile.company,
            total_rows=total_rows,
            is_single_upload=total_rows == 1,
            has_header_row=has_header,
        )

        if filename:
            upload_skip_trace.path = path
            upload_skip_trace.uploaded_filename = filename

        upload_skip_trace.save(update_fields=['path', 'uploaded_filename'])
        return upload_skip_trace

    @property
    def estimated_push_rows(self):
        """
        Return the amount of properties rows that would be pushed to a campaign.
        """
        count = self.property_set.count()
        if not count:
            count = self.skiptraceproperty_set.count()

        return count

    @property
    def estimated_new_prospects(self):
        """
        Returns the amount of new properties in this upload that will be pushed to a campaign.
        """
        from sherpa.models import Prospect
        props = self.property_set.all().values_list('id', flat=True)
        # Return counts of properties that have at least one new Prospect.
        prospect_count = Prospect.objects.filter(
            prop__id__in=props,
            upload_duplicate=False,
        ).values('prop__id').distinct().count()

        if not prospect_count:
            full_count = self.estimated_push_rows
            phones = self.skiptraceproperty_set.all().values_list(
                'returned_phone_1',
                'returned_phone_2',
                'returned_phone_3',
            )
            phones_tuple = [phone for phone in phones]
            phones_flat = [phone for phone in phones_tuple]
            prospect_count = Prospect.objects.filter(
                phone_raw__in=phones_flat,
                upload_duplicate=False,
            ).values('prop__id').distinct().count()
            prospect_count = full_count - prospect_count

        return prospect_count

    @property
    def push_to_campaign_percent(self):
        """
        Return integer as a percentage of how far the push to campaign is.
        """
        if self.push_to_campaign_status == self.PushToCampaignStatus.COMPLETE:
            return 100
        current = self.last_row_push_to_campaign
        total = self.total_rows_push_to_campaign
        return 0 if not total or not current else int(current / total * 100)

    def charge(self):
        if not self.transaction:
            return

        trans = self.transaction

        if not trans.is_failed and trans.is_authorized and not trans.is_charged:
            if self.total_billable_hits > 0:
                trans.charge(self.cost)
            else:
                trans.failure_reason = '0 billable hits on this skip trace'
                trans.save(update_fields=['failure_reason'])

    def authorized_successful(self):
        """
        Calculate price and authorize transaction. Return True if successful.
        """
        # If this is a single upload, return True. Transactions are handled differently.
        if self.is_single_upload:
            return True

        authorize_amount = (self.total_rows * Decimal(float(1.00))) * Decimal(
            self.company.skip_trace_price)
        return self.authorize_transaction(authorize_amount)

    def authorize_transaction(self, amount, push_to_campaign=False):
        """
        Authorize transaction for given amount.
        """
        from billing.models import Transaction

        # Return true if company is exempt from billing, there's no transaction to authorize.
        if self.company.is_billing_exempt:
            return True

        transaction_desc = 'Sherpa Upload Fee' if push_to_campaign else 'Sherpa Skip Trace Fee'
        transaction = Transaction.authorize(self.company, transaction_desc, amount)
        if push_to_campaign:
            self.push_to_campaign_transaction = transaction
            update_fields = 'push_to_campaign_transaction'
        else:
            self.transaction = transaction
            update_fields = 'transaction'
        self.save(update_fields=[update_fields])

        if not transaction.is_authorized and not settings.TEST_MODE:
            return False
        return True

    def charge_push_to_campaign_transaction(self, campaign_prospect_count):
        """
        Charge push to campaign transaction for number of prospects given.
        """

        # If there's no transaction or company is exempt to billing, there's no charge.
        if not self.push_to_campaign_transaction or self.company.is_billing_exempt:
            return

        trans = self.push_to_campaign_transaction
        if not trans.is_failed and trans.is_authorized and not trans.is_charged:
            # Amount to charge can be less than authorized amount if campaign
            # already has prospect and user chose to push new prospects only - recalculate.
            calculated_amount, exceeds_count = \
                get_upload_additional_cost(self.company, campaign_prospect_count, self)

            if calculated_amount > 0:
                trans.charge(calculated_amount)

    def rows_to_push_to_campaign(self, import_type=''):
        """
        Total rows to push is all rows in upload unless import type is new.
        """
        from .skiptraceproperty import SkipTraceProperty
        if import_type == 'new':
            return SkipTraceProperty.objects.filter(upload_skip_trace=self,
                                                    returned_phone_1__isnull=False,
                                                    existing_match_prospect_id=None).count()

        return SkipTraceProperty.objects.filter(upload_skip_trace=self,
                                                returned_phone_1__isnull=False).count()

    def upload_single(self):
        """
        Upload single skip trace.
        """
        error = None
        if self.total_hits and not self.total_existing_matches:
            error = self.company.debit_sherpa_balance(1)
        if error:
            return error
        self.single_upload_authorized = True
        self.save(update_fields=['single_upload_authorized'])

    @property
    def cost(self):
        """
        Cost of upload to use for calculations.
        """
        if self.is_single_upload:
            return settings.SHERPA_CREDITS_CHARGE * self.total_billable_hits

        cost = self.company.skip_trace_price * self.total_billable_hits
        if cost and cost < settings.MIN_SKIP_TRACE_CHARGE:
            return settings.MIN_SKIP_TRACE_CHARGE
        return cost

    @property
    def cost_formatted(self):
        """
        Cost formatted with 2 decimal places to use for display.
        """
        return '%.2f' % self.cost

    @property
    def estimate_range(self):

        if self.is_single_upload:
            return f'$0.00 - ${settings.SHERPA_CREDITS_CHARGE} (from your skip trace credits)'

        price = self.company.skip_trace_price

        low_percentage = Decimal(float(.90))
        high_percentage = Decimal(float(1.00))
        estimate_low = (self.total_rows * low_percentage) * Decimal(price)
        estimate_low = "%.2f" % estimate_low
        estimate_high = (self.total_rows * high_percentage) * Decimal(price)
        estimate_high = "%.2f" % estimate_high
        return "$%s - $%s" % (estimate_low, estimate_high)

    @property
    def existing_match_savings(self):
        if self.total_existing_matches > 0 and self.company.skip_trace_price:
            if self.is_single_upload:
                return f'${settings.SHERPA_CREDITS_CHARGE}'
            savings = self.total_existing_matches * self.company.skip_trace_price
            return "$%.2f" % savings

        return "0"

    @property
    def hit_rate(self):
        """
        Calculate percentage of hits compared to total uploaded.
        """
        if self.last_row_processed > 0 and self.total_hits > 0:
            percentage = (float(self.total_hits) / self.last_row_processed) * 100
            return "%.0f" % percentage
        else:
            return 0

    @property
    def has_valid_idi_token(self):
        """
        Return whether IDI token is valid.
        """
        is_expired = \
            self.last_idi_token_reset and \
            (django_tz.now() - self.last_idi_token_reset).seconds > 1500
        if not self.idi_token or is_expired:
            return False
        return True

    def __str__(self):
        return "%s - %s" % (self.company, self.created)

    def restart(self):
        """
        Sometimes skip trace uploads will get stuck or error out and need to be restarted.
        """
        from skiptrace.tasks import start_skip_trace_task, skip_trace_push_to_campaign_task

        self.stop_upload = False
        self.stop_push_to_campaign = False
        self.save(update_fields=['stop_upload', 'stop_push_to_campaign'])

        if self.status in ["error", "paused"]:
            start_skip_trace_task.delay(self.id)

        if self.push_to_campaign_status in [
            self.PushToCampaignStatus.ERROR,
            self.PushToCampaignStatus.PAUSED,
        ]:
            skip_trace_push_to_campaign_task.delay(self.id)
