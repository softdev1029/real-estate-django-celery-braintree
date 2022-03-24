import uuid

from model_utils import FieldTracker
from simplecrypt import decrypt, encrypt
from twilio.base.exceptions import TwilioException

from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.functional import cached_property

from core import models
from phone.choices import Provider

User = get_user_model()


class CompanyChurn(models.Model):
    """
    Certain statistics about a company that indicates how likely they are to churn and helps
    indicate if intervention would be beneficial.

    The data here takes a while to get since it has many braintree calls and is updated nightly
    through the `update_churn_stats` task.
    """
    company = models.OneToOneField('sherpa.Company', related_name='churn', on_delete=models.CASCADE)
    days_until_subscription = models.SmallIntegerField(null=True)
    prospect_upload_percent = models.SmallIntegerField(null=True)

    def __str__(self):
        return self.company.name

    class Meta:
        verbose_name_plural = 'Company churn'


class CompanyGoal(models.Model):
    """
    CompanyGoal represents a business' goal for budgets, campaigns, etc...
    over a duration of time.
    """
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    budget = models.DecimalField(max_digits=13, decimal_places=2)
    leads = models.IntegerField()
    avg_response_time = models.IntegerField()
    new_campaigns = models.IntegerField()
    delivery_rate_percent = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-id',)

    def __str__(self):
        return f"{self.company.name} goal for {self.start_date}"


class CompanyUploadHistory(models.Model):
    """
    History of monthly upload usage by billing period for a `Company`
    """
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    start_billing_date = models.DateField()
    end_billing_date = models.DateField()
    upload_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ('company', 'start_billing_date')
        ordering = ('company', '-end_billing_date')
        verbose_name_plural = 'Monthly Upload Usage'


class FileBaseModel(models.Model):
    """
    Base model handling all file related matters.
    """
    class Status:
        AUTO_STOP = 'auto_stop'
        COMPLETE = 'complete'
        ERROR = 'error'
        CANCELLED = 'cancelled'
        PAUSED = 'paused'
        RUNNING = 'running'
        SENT_TO_TASK = 'sent_to_task'
        SETUP = 'setup'

        CHOICES = (
            (AUTO_STOP, 'Auto Stop'),
            (COMPLETE, 'Complete'),
            (ERROR, 'Error'),
            (CANCELLED, 'Cancelled'),
            (PAUSED, 'Paused'),
            (RUNNING, 'Running'),
            (SENT_TO_TASK, 'Sent to Task'),
            (SETUP, 'Setup'),
        )

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    company = models.ForeignKey('sherpa.Company', null=True, blank=True, on_delete=models.CASCADE)

    status = models.CharField(default=Status.SETUP, max_length=16, choices=Status.CHOICES)
    last_row_processed = models.IntegerField(default=0)
    total_rows = models.IntegerField(default=0)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def percentage(self):
        if self.total_rows > 0:
            return round(float(self.last_row_processed) / float(self.total_rows) * 100)
        return 0


def upload_path(instance, filename):
    if instance.company:
        return f'companies/{instance.company.uuid}/uploads/{filename}'
    # Litigator uploads do not have a user profile account associated with them.
    return f'litigator_uploads/{filename}'


class UploadBaseModel(FileBaseModel):
    """
    Base abstract model for our shared functionality on upload models.
    """
    uploaded_filename = models.CharField(null=True, blank=True, max_length=255)
    path = models.CharField(null=True, blank=True, max_length=255)
    stop_upload = models.BooleanField(default=False)
    file = models.FileField(upload_to=upload_path, null=True, blank=True)

    class Meta:
        abstract = True


def download_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/companies/<company uuid>/downloads/<filename>
    return f'companies/{instance.company.uuid}/downloads/{filename}'


class DownloadHistory(FileBaseModel):
    """
    Model that manages the history of downloads within a company.  The uuid is used to poll data
    from the frontend to determine if the users download is ready.
    """
    class DownloadTypes:
        CAMPAIGN_PROSPECT = 'campaign_prospect'
        PROSPECT = 'prospect'
        SKIPTRACE = 'skiptrace'
        DNC = 'dnc'
        CAMPAIGN = 'campaign'
        CAMPAIGN_META_STATS = 'campaign_meta_stats'
        PROFILE_STATS = 'profile_stats'
        PROPERTY = 'property'

        CHOICES = (
            (CAMPAIGN_PROSPECT, 'CampaignProspect Export'),
            (PROSPECT, 'Prospect Export'),
            (SKIPTRACE, 'Skip Trace'),
            (DNC, 'DNC'),
            (CAMPAIGN, 'Campaign Export'),
            (CAMPAIGN_META_STATS, 'CampaignMetaStats Export'),
            (PROFILE_STATS, 'ProfileStats Export'),
            (PROPERTY, 'Property Export'),
        )
    uuid = models.UUIDField(default=uuid.uuid4, db_index=True)
    download_type = models.CharField(choices=DownloadTypes.CHOICES, max_length=32)
    file = models.FileField(upload_to=download_path)
    filters = JSONField(encoder=DjangoJSONEncoder)
    is_bulk = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'Download history'

    def save(self, *args, **kwargs):
        if self.id is None:
            self.is_hidden = self.created_by.is_staff and not self.company.is_cedar_crest
        super().save(*args, **kwargs)


class TelephonyConnection(models.Model):
    """
    Model to store connections to company specified Telephony services.
    """
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    api_key = models.TextField()
    api_secret = models.TextField()
    random_key = models.UUIDField(default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=16, choices=Provider.CHOICES, default=Provider.TWILIO)

    tracker = FieldTracker()

    class Meta:
        unique_together = ('company', 'provider')

    def get_secret(self):
        """
        Return API secret to be used to connect.
        """
        return decrypt(str(self.random_key).encode(), eval(self.api_secret)).decode()

    @cached_property
    def client(self):
        """
        Gets correct client for this connection.
        """
        from sms.clients import get_client
        return get_client(self.provider, self.api_key, self.get_secret())

    def sync(self, check_for_duplicates=True):
        """
        Updates Sherpa data with data stored on this connection.

        :param check_for_duplicates bool: Determines if duplicate should be checked.  Used to
        prevent additional sync calls.
        """
        from core.utils import clean_phone
        from sms.utils import get_webhook_url
        from sherpa.models import PhoneNumber, Market

        numbers = self.client.get_numbers()
        voice_url = get_webhook_url(self.provider, 'voice')
        update_data = {
            'sms_url': get_webhook_url(self.provider, 'incoming'),
            'voice_url': voice_url,
            'status_callback': voice_url,
        }
        market, _ = Market.objects.get_or_create(
            company=self.company,
            name='Twilio',
        )

        if check_for_duplicates:
            self.check_duplicates([clean_phone(number) for number in numbers])

        current_phones = PhoneNumber.objects.filter(company=self.company, provider=self.provider)

        updated = []
        for number in numbers:
            phone, created = PhoneNumber.objects.get_or_create(
                company=self.company,
                market=market,
                phone=clean_phone(number.phone_number),
                provider=self.provider,
            )
            if created:
                self.client.update_number(number.sid, **update_data)

            updated.append(phone.phone)

        # Delete phones that were removed from this account.
        current_phones.exclude(phone__in=updated).delete()

    def check_duplicates(self, numbers):
        """
        Checks for the existence of duplicated numbers in other company accounts and will attempt
        to resync their account but will delete their numbers if sync throws an exception.

        :param numbers list: List of cleaned phone numbers to check.
        """
        from sherpa.models import Company, PhoneNumber
        existing_duplicate_phones_company = PhoneNumber.objects.filter(
            phone__in=numbers,
            status=PhoneNumber.Status.ACTIVE,
            provider=self.provider,
        ).exclude(company_id=self.company_id).values('company_id').distinct()
        if existing_duplicate_phones_company.exists():
            for company in Company.objects.filter(pk__in=existing_duplicate_phones_company):
                delete_numbers = False
                company_tel_conn = company.telephonyconnection_set.get(provider=self.provider)

                if company_tel_conn.api_key == self.api_key:
                    # We have some clients with more than one company, or that might come back
                    # and register as a new company, but attempt to reuse the same Twilio account
                    # In this case, the last company to setup/sync the account keeps the numbers
                    delete_numbers = True
                else:
                    try:
                        # Do not check for duplicates as it'll result in a never ending sync loop.
                        company_tel_conn.sync(
                            check_for_duplicates=False,
                        )
                    except TwilioException:
                        delete_numbers = True

                if delete_numbers:
                    company.phone_numbers.filter(
                        provider=self.provider,
                        phone__in=numbers,
                    ).delete()

    def save(self, *args, **kwargs):
        """
        Encode API secret before storing in database.
        """
        if self.tracker.has_changed('api_secret'):
            key = str(self.random_key).encode()
            self.api_secret = encrypt(key, self.api_secret)

        return super(TelephonyConnection, self).save(*args, **kwargs)


class CompanyPodioCrm(models.Model):
    """
    We keep track of the users integration information here. We keep
    track of their org, workspace and app to properly sync the
    prospect data to the correct app on Podio.
    """
    organization = models.PositiveIntegerField(null=True, help_text="Podio Organization id")
    workspace = models.PositiveIntegerField(null=True, help_text="Podio Workspace id")
    application = models.PositiveIntegerField(null=True, help_text="Podio Application id")

    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)

    access_token = models.CharField(null=True, max_length=64)
    refresh_token = models.CharField(null=True, max_length=64)
    expires_in_token = models.PositiveIntegerField(null=True)


class PodioFieldMapping(models.Model):
    """
    Stores information about the field mapping that allows the
    export mechanism to provide only the mapped fields.
    """
    company = models.OneToOneField('sherpa.Company', on_delete=models.CASCADE)
    fields = JSONField(encoder=DjangoJSONEncoder, null=True)


class PodioProspectItem(models.Model):
    """
    Stores information of prospects that have been synced to podio
    already.  Used in the export mechanism to avoid creating multiple
    records on podio.
    """
    prospect = models.OneToOneField('sherpa.Prospect', on_delete=models.CASCADE)
    item_id = models.PositiveIntegerField()


class CompanyPropStackFilterSettings(models.Model):
    """
    Company wise property stacker filter settings.
    """
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    filter_name = models.CharField(max_length=120)
    filter_json = JSONField(encoder=DjangoJSONEncoder)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('company', 'filter_name')
        verbose_name_plural = 'Company stacker filters'

    def __str__(self):
        return self.filter_name
