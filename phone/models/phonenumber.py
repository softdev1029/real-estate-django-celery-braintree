from django.utils import timezone as django_tz
from django.utils.functional import cached_property

from accounts.models.company import Company
from core import models
from phone.choices import Provider

__all__ = (
    'PhoneNumber',
)


class PhoneNumber(models.Model):
    """
    Record of the phone number purchased/reserved from our providers.
    """
    class Status:
        ACTIVE = 'active'
        PENDING = 'pending'
        INACTIVE = 'inactive'
        RELEASED = 'released'
        COOLDOWN = 'cooldown'

        CHOICES = (
            (ACTIVE, 'Active'),
            (PENDING, 'Pending'),
            (INACTIVE, 'Inactive'),
            (RELEASED, 'Released'),
            (COOLDOWN, 'Cooldown'),
        )

    company = models.ForeignKey(Company, related_name='phone_numbers', on_delete=models.CASCADE)
    market = models.ForeignKey('Market', related_name='phone_numbers', on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True)
    phone = models.CharField(max_length=16, db_index=True)

    # Save the twilio sid for a certain time, just in case.
    provider_id = models.CharField(max_length=125, blank=True)

    status = models.CharField(
        default=Status.ACTIVE,
        max_length=16,
        db_index=True,
        choices=Status.CHOICES,
    )
    provider = models.CharField(max_length=16, choices=Provider.CHOICES, default=Provider.TELNYX)

    last_send_utc = models.DateTimeField(null=True, blank=True)
    last_received_utc = models.DateTimeField(null=True, blank=True)
    total_sent = models.IntegerField(default=0)
    total_sent_today = models.IntegerField(default=0)
    total_opt_outs = models.IntegerField(default=0)
    total_auto_dead = models.IntegerField(default=0)

    # Overall historical delivery percentage supplied by telnyx.
    delivery_percentage = models.DecimalField(null=True, blank=True, decimal_places=2, max_digits=3)

    # Overall delivery percentage while in the Sherpa system.
    sherpa_delivery_percentage = models.DecimalField(
        null=True, blank=True, decimal_places=2, max_digits=3)

    @cached_property
    def client(self):
        """
        Get client based on provider
        """
        from sms.clients import get_client
        return get_client(provider=self.provider, company_id=self.company_id)

    @property
    def health(self):
        """
        Return health ("good", "moderate", "poor") based on delivery percentage in the sherpa
        system.
        """
        status_exclude_check = self.status in [PhoneNumber.Status.RELEASED]
        if status_exclude_check or not self.sherpa_delivery_percentage:
            return "unknown"
        if self.sherpa_delivery_percentage < .7:
            return "poor"
        if self.sherpa_delivery_percentage < .85:
            return "moderate"
        return "good"

    @property
    def phone_display(self):
        """
        Shows a "reader friendly" version of the phone number.
        """
        if self.phone is None:
            return ""
        if len(self.phone) == 10:
            return "(%s) %s-%s" % (self.phone[:3], self.phone[3:6], self.phone[6:])
        else:
            return ""

    @property
    def full_number(self):
        """
        Returns the fully qualified number with country code.
        """
        return f'+1{self.phone}'

    @property
    def can_release(self):
        """
        Returns a boolean if the phone number is in a state that can be released.
        """
        if self.provider == Provider.TWILIO or not self.provider_id:
            return False

        if self.status in [self.Status.ACTIVE, self.Status.INACTIVE]:
            return True

        return False

    def replace(self):
        """
        Release a phone number and replace it with another number in the same market without charge.

        Not used from within the code, but was developed during the great spoofing of feb 2020.
        """
        from phone.utils import process_number_order

        if self.provider != Provider.TELNYX:
            return

        # Release the number.messaging_client
        self.client.delete_number(self.provider_id)
        self.status = self.Status.RELEASED
        self.save()

        # Purchase a new number, without charging.
        market = self.market
        available_response = self.client.get_available_numbers(market.area_code1, limit=1)
        available_list = [instance.get('phone_number') for instance in available_response['data']]
        process_number_order(market, available_list)

    def activate(self):
        """
        Sometimes phone numbers are not marked as activated even though they are ready in Telnyx.

        This will mark this number active and other pending numbers in this number's market.
        """
        if self.provider != Provider.TELNYX:
            return

        # Get all pending numbers in this number's market
        pending_numbers = PhoneNumber.objects.filter(
            status=PhoneNumber.Status.PENDING, market=self.market)

        # If the number's active on Telnyx, finish activating it so it can be used.
        for phone_number in pending_numbers:
            numbers_response = self.client.list_numbers(phone_number=phone_number)
            # If there's no good response, the number isn't ready.
            if numbers_response.status_code != 200:
                return

            # If 'active' on Telnyx activate on our system and add connection id on Telnyx.
            response_data = numbers_response.json().get('data')
            if response_data and response_data[0].get('status') == self.Status.ACTIVE:
                provider_id = response_data[0].get('id')
                phone_number.status = PhoneNumber.Status.ACTIVE
                phone_number.provider_id = provider_id
                phone_number.save(update_fields=['status', 'provider_id'])

    def record_sent(self):
        """
        After receiving a status webhook, we need to record various stats about who sent it.

        This happens after the status callback is received.
        """
        # Update stats about the sent mesage.
        self.last_send_utc = django_tz.now()
        self.total_sent = self.total_sent + 1
        self.total_sent_today = self.total_sent_today + 1
        self.save(update_fields=['last_send_utc', 'total_sent', 'total_sent_today'])

    def release(self):
        """
        Release the number from provider and update local sherpa data.
        """
        if self.provider != Provider.TELNYX:
            return

        if self.provider_id:
            self.client.delete_number(self.provider_id)

        self.status = self.Status.RELEASED
        self.sherpa_delivery_percentage = None
        self.save(update_fields=['status', 'sherpa_delivery_percentage'])

        self.market.company.update_phone_number_addons()

    def __str__(self):
        return self.phone

    class Meta:
        app_label = 'sherpa'
