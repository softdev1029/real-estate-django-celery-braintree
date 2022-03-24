from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone as django_tz

from accounts.models.company import Company
from campaigns.models.campaigns import Campaign, CampaignProspect, Prospect
from core import models

__all__ = (
    'SMSMessage',
)

User = get_user_model()


class SMSMessage(models.Model):
    """
    Record created with every sms message sent or received through Sherpa.
    """
    prospect = models.ForeignKey(
        Prospect, null=True, on_delete=models.CASCADE, related_name='messages')
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    market = models.ForeignKey('Market', null=True, blank=True, on_delete=models.CASCADE)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    response_from_rep = models.ForeignKey(
        User, null=True,
        blank=True,
        related_name='response_from_rep_name',
        on_delete=models.CASCADE,
    )
    initial_message_sent_by_rep = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name='initial_message_sent_by_rep_name',
        on_delete=models.CASCADE,
    )

    # campaign is only saved for messages sent from bulk send
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL)
    template = models.ForeignKey(
        'sherpa.SMSTemplate', null=True, blank=True, on_delete=models.SET_NULL)
    stats_batch = models.ForeignKey(
        'sherpa.StatsBatch', blank=True, null=True, on_delete=models.SET_NULL,
        related_name='messages')

    provider_message_id = models.CharField(max_length=64, blank=True, db_index=True)
    dt = models.DateTimeField(auto_now_add=True, db_index=True)
    from_number = models.CharField(max_length=255, db_index=True)

    to_number = models.CharField(max_length=255)
    message = models.TextField()
    unread_by_recipient = models.BooleanField(default=False)
    media_url = models.CharField(max_length=255, null=True, blank=True)
    from_prospect = models.BooleanField(default=False)
    response_dt = models.DateTimeField(null=True, blank=True)
    response_time_seconds = models.IntegerField(default=0)

    # Probably can remove after slight refactors.
    message_status = models.CharField(null=True, blank=True, max_length=120, db_index=True)
    has_second_send_attempt = models.BooleanField(default=False)
    dt_local = models.DateTimeField(null=True, blank=True)
    num_media = models.CharField(max_length=255, null=True, blank=True)
    file_extension = models.CharField(max_length=255, null=True, blank=True)
    contact_number = models.CharField(max_length=255, db_index=True)
    our_number = models.CharField(max_length=255)

    def save(self, *args, **kwargs):
        """
        Update aggregated stats for the prospect after updating/creating an sms message.
        """
        # Don't allow message to be saved with NUL (0x00) characters
        self.message = self.message.replace('\x00', '')
        if self.prospect:
            sms_sent_count_raw = SMSMessage.objects.filter(
                ~Q(id=self.id),
                ~Q(id=None),
                Q(prospect=self.prospect),
                ~Q(from_prospect=True),
            ).count()
            if not self.from_prospect:
                sms_sent_count = sms_sent_count_raw + 1
            else:
                sms_sent_count = sms_sent_count_raw

            sms_received_count_raw = SMSMessage.objects.filter(
                ~Q(id=self.id),
                ~Q(id=None),
                Q(prospect=self.prospect),
                Q(from_prospect=True),
            ).count()
            if self.from_prospect:
                sms_received_count = sms_received_count_raw + 1
            else:
                sms_received_count = sms_received_count_raw

            self.prospect.total_sms_sent_count = sms_sent_count
            self.prospect.total_sms_received_count = sms_received_count

            self.prospect.save(update_fields=['total_sms_sent_count',
                                              'total_sms_received_count'])

        # Use Denver for the timezone - make dynamic later
        if self.dt_local is None:
            self.dt_local = django_tz.now()

        # If there's a media url but no file extension, get file extension.
        if self.media_url and not self.file_extension:
            self.file_extension = "." + self.media_url.split(".")[-1]

        super(SMSMessage, self).save(*args, **kwargs)

    @property
    def from_name(self):
        """
        Return the display of who the message was from, either company or prospect.
        """
        if self.from_prospect:
            return self.prospect.get_full_name() if self.prospect else ''

        sent_from = self.user or self.initial_message_sent_by_rep
        if sent_from:
            return sent_from.get_full_name()

        # This shouldn't really happen, but in case there is no user associated with the message.
        return ''

    @property
    def campaign_prospect(self):
        if not self.prospect or not self.campaign:
            return None

        try:
            CampaignProspect.objects.get(prospect=self.prospect, campaign=self.campaign)
        except CampaignProspect.DoesNotExist:
            # It's possible that the campaign prospect has moved to a different followup campaign.
            return None

    @property
    def is_bulk_message(self):
        """
        Determine if the sms message was sent as a bulk message.
        """
        return True if self.campaign else False

    @property
    def is_delivered(self):
        """
        Determine if an sms message was delivered through its relation to the twilio result.
        """
        return self.result.status == 'delivered'

    def update_cp_stats(self, message_status, error_code):
        """
        Update status and error codes for prospects.
        """
        cp = self.campaign_prospect

        if not cp:
            return

        if message_status:
            cp.last_message_status = message_status
        if error_code:
            cp.last_message_error = error_code
        cp.save(update_fields=['last_message_status', 'last_message_error'])

    class Meta:
        app_label = 'sherpa'


@receiver(post_save, sender=SMSMessage)
def set_unread_indicators(sender, instance, signal, *args, **kwargs):
    """
    When an SMSMessage is saved, we need to check whether the prospect should be marked as read.
    """
    # skip signal if any of the following conditions are met.
    if any([
        instance.campaign and kwargs.get('created'),
        not kwargs.get('created'),
        not instance.prospect,
        instance.unread_by_recipient,
        SMSMessage.objects.filter(prospect=instance.prospect, unread_by_recipient=True).exists(),
    ]):
        return

    instance.prospect.mark_as_read()
