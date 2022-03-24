from django.db.models import Q

from campaigns.models.campaigns import CampaignProspect
from core import models
from phone.choices import Provider

__all__ = (
    'StatsBatch',
)


class StatsBatch(models.Model):
    """
    Batches sms send/recieve stats into groups of 100.

    This is used to monitor delivery rates and spot issue such as "bad" group of numbers within
    campaign.
    """
    campaign = models.ForeignKey('Campaign', null=True, blank=True, on_delete=models.CASCADE)

    # Parent market should be removed and just get through Market if needed.
    parent_market = models.ForeignKey(
        'AreaCodeState', null=True, blank=True, on_delete=models.CASCADE)
    market = models.ForeignKey('Market', null=True, blank=True, on_delete=models.CASCADE)

    provider = models.CharField(max_length=16, choices=Provider.CHOICES, default=Provider.TWILIO)
    created_utc = models.DateTimeField(auto_now_add=True)
    batch_number = models.IntegerField(default=0)

    # Aggregated fields.
    sent = models.IntegerField(default=0)
    delivered = models.IntegerField(default=0)
    received = models.IntegerField(default=0)
    received_dead_auto = models.IntegerField(default=0)
    send_attempt = models.IntegerField(default=0)

    # First/Last send should each have 1 field instead of 2.
    first_send_utc = models.DateTimeField(null=True, blank=True)
    last_send_utc = models.DateTimeField(null=True, blank=True)

    # These skip records should be moved out into own model `MessageSkip`.
    skipped_has_previous_response = models.IntegerField(default=0)
    skipped_msg_threshold_days = models.IntegerField(default=0)
    skipped_internal_dnc = models.IntegerField(default=0)
    skipped_litigator = models.IntegerField(default=0)
    skipped_opted_out = models.IntegerField(default=0)
    skipped_att = models.IntegerField(default=0)
    skipped_verizon = models.IntegerField(default=0)
    skipped_outgoing_not_set = models.IntegerField(default=0)
    skipped_wrong_number = models.IntegerField(default=0)
    skipped_force = models.IntegerField(default=0)

    class Meta:
        app_label = 'sherpa'
        ordering = ('-created_utc',)

    @property
    def skipped_carrier(self):
        return self.skipped_att + self.skipped_verizon

    @property
    def total_skipped(self):
        return self.skipped_has_previous_response + \
            self.skipped_msg_threshold_days + \
            self.skipped_internal_dnc + \
            self.skipped_litigator + \
            self.skipped_opted_out + \
            self.skipped_att + \
            self.skipped_wrong_number + \
            self.skipped_force + \
            self.skipped_verizon

    @property
    def response_rate(self):
        if self.received > 0 and self.delivered > 0:
            return round(self.received / self.delivered * 100)
        return 0

    @property
    def delivered_percent(self):
        total_non_skipped = self.send_attempt - self.total_skipped
        if self.delivered > 0 and total_non_skipped > 0:
            return round(self.delivered / total_non_skipped * 100)
        return 0

    # added this query becuase sent above wasn't adding up right
    @property
    def total_sent(self):
        return CampaignProspect.objects.filter(Q(sent=True), Q(stats_batch=self)).count()

    @property
    def last_send(self):
        """
        Return the last send datetime in the batch stats.

        Previously there were several renditions of this with local and utc, which weren't actually
        correct... but this will always return an aware datetime object with the last sent datetime
        for the batch.

        By only exposing this one field to the frontend, we can more easily remove all the other
        *_utc and *_local datetime fields and just use a single source of truth.
        """
        return self.last_send_utc

    @property
    def results(self):
        """
        Return a queryset of the `SMSResult` objects associated with this StatsBatch.
        """
        from sms.models import SMSResult

        return SMSResult.objects.filter(sms__stats_batch=self)

    @property
    def skip_details(self):
        return {
            'previous_response': self.skipped_has_previous_response,
            'threshold': self.skipped_msg_threshold_days,
            'dnc': self.skipped_internal_dnc,
            'litigator': self.skipped_litigator,
            'opted_out': self.skipped_opted_out,
            'carrier': self.skipped_carrier,
            'wrong_number': self.skipped_wrong_number,
            'forced': self.skipped_force,
        }
