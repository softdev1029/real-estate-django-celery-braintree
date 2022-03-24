from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction as django_transaction
from django.utils import timezone as django_tz

from accounts.models.company import Company
from campaigns.models.campaigns import Campaign, Prospect
from companies.models import UploadBaseModel
from core import models
from sms.utils import fetch_phonenumber_info

__all__ = (
    'LitigatorList', 'LitigatorReportQueue', 'PhoneType', 'ReceiptSmsDirect',
    'UploadLitigatorList',
)

User = get_user_model()


class ReceiptSmsDirect(models.Model):
    """
    Receipt created with every "bulk" send. Ensures 2 "bulk" messages don't get sent from
    same campaign to same prospect and to measure the 5-day rule for outgoing messages sent to a
    phone number.
    """
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    phone_raw = models.CharField(null=True, blank=True, max_length=255, db_index=True)
    sent_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'sherpa'


class PhoneType(models.Model):
    """
    Stores data gathered about a phone number.
    """
    class Type:
        MOBILE = 'mobile'
        VOIP = 'voip'
        LANDLINE = 'landline'
        NA = 'na'

        CHOICES = (
            (MOBILE, 'Mobile'),
            (VOIP, 'VOIP'),
            (LANDLINE, 'Landline'),
            (NA, 'Not Applicable'),
        )

    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    # campaign is used for cost tracking on campaign
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.CASCADE)
    checked_datetime = models.DateTimeField(auto_now_add=True)
    phone = models.CharField(max_length=16, unique=True)

    # aww20200121 Only 37K / 41M with null type
    type = models.CharField(null=True, blank=True, max_length=16, choices=Type.CHOICES)
    carrier = models.CharField(null=True, blank=True, max_length=255)

    # aww20200224 only 764K / 45M have processed
    is_processed = models.BooleanField(default=False)
    last_carrier_lookup = models.DateField(
        null=True,
        blank=True,
        help_text="Date when this phones carrier was last checked against Telnyx.",
    )

    @property
    def last_lookup_date(self):
        """
        Returns the last carrier lookup or when this record was created.
        """
        return self.last_carrier_lookup or self.checked_datetime.date()

    @property
    def should_lookup_carrier(self):
        """
        Returns True if the records last_lookup_date is older than 90 days.
        """
        return (django_tz.now().date() - self.last_lookup_date).days > 30 * 3

    def lookup_phone_type(self):
        """
        Lookup phone type and carrier.
        """
        try:
            # Use the default client since we use it for all lookups.
            carrier = fetch_phonenumber_info(self.phone)
            phone_type = carrier['type']
            phone_carrier = carrier['name']

            self.type = phone_type if phone_type else 'na'
            self.carrier = phone_carrier
            self.last_carrier_lookup = django_tz.now().date()
            self.save(update_fields=['last_carrier_lookup', 'type', 'carrier'])

            return None
        except Exception:
            return True

    class Meta:
        app_label = 'sherpa'


class LitigatorList(models.Model):
    """
    List of phone numbers that need to be "skipped" on sends.

    Jason/Sherpa updates this list about once per week.
    """
    class Types:
        LITIGATOR = 'Litigator'
        COMPLAINER = 'Complainer'
        REPORTED = 'Reported'

        CHOICES = (
            (LITIGATOR, LITIGATOR),
            (COMPLAINER, COMPLAINER),
            (REPORTED, REPORTED),
        )

    created = models.DateTimeField(auto_now_add=True)
    phone = models.CharField(max_length=16, unique=True, db_index=True)
    type = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        choices=Types.CHOICES,
    )

    class Meta:
        app_label = 'sherpa'


class LitigatorReportQueue(models.Model):
    """
    Holds information about user submitted litigators that Sherpa will verify.
    """
    class Status:
        PENDING = 'pending'
        APPROVED = 'approved'
        DECLINED = 'declined'

        CHOICES = (
            (PENDING, 'Pending'),
            (APPROVED, 'Approved'),
            (DECLINED, 'Declined'),
        )

    created = models.DateTimeField(auto_now_add=True)
    prospect = models.OneToOneField('sherpa.Prospect', on_delete=models.CASCADE)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='reporter',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    status = models.CharField(max_length=16, choices=Status.CHOICES, default=Status.PENDING)
    phone = models.CharField(max_length=16, null=True, blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='report_handler',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    handled_on = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(null=True, blank=True, max_length=256)
    conversation_link = models.CharField(null=True, blank=True, max_length=100)

    def __str__(self):
        return f"{self.prospect} - {self.prospect.phone_raw}"

    class Meta:
        app_label = 'sherpa'

    def approve(self, sherpa_user):
        with django_transaction.atomic():
            LitigatorList.objects.get_or_create(
                phone=self.prospect.phone_raw,
                defaults={
                    'type': LitigatorList.Types.REPORTED,
                },
            )
            self.status = self.Status.APPROVED
            self.handled_by = sherpa_user
            self.handled_on = django_tz.now()
            self.save(update_fields=['status', 'handled_by', 'handled_on'])

    def decline(self, sherpa_user):
        self.status = self.Status.DECLINED
        self.handled_by = sherpa_user
        self.handled_on = django_tz.now()
        self.save(update_fields=['status', 'handled_by', 'handled_on'])

    @staticmethod
    def submit(prospect: Prospect, user: User = None):
        # Only submit if the prospect is not already marked as litigator
        # Can't create queue entry if there is already one for the prospect because
        # there is a unique contraint... TODO: remove and change this?
        if not any((LitigatorList.objects.filter(phone=prospect.phone_raw).exists(),
                    LitigatorReportQueue.objects.filter(prospect=prospect).exists())):
            params = {"prospect": prospect}
            if user is not None:
                params["submitted_by"] = user
            LitigatorReportQueue.objects.create(**params)


class UploadLitigatorList(UploadBaseModel):
    """
    Tracks the LitigatorList upload performed by Jason/Sherpa.
    """
    last_numbers_saved = models.IntegerField(default=0)
    litigator_list_type = models.CharField(null=True, blank=True, max_length=16)
    confirmation_email_sent = models.BooleanField(default=False)

    class Meta:
        app_label = 'sherpa'
