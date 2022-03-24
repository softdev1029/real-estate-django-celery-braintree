from core import models
from ..managers import CampaignDailyStatsManager


class CampaignDailyStats(models.Model):
    """
    Create aggregated daily stats for campaigns.
    """
    campaign = models.ForeignKey('sherpa.Campaign', on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    new_leads = models.PositiveSmallIntegerField()
    skipped = models.PositiveSmallIntegerField()
    delivered = models.PositiveSmallIntegerField()
    sent = models.PositiveSmallIntegerField()
    auto_dead = models.PositiveSmallIntegerField()
    responses = models.PositiveSmallIntegerField()

    objects = CampaignDailyStatsManager()

    class Meta:
        unique_together = ('campaign', 'date')


class CampaignAggregatedStats(models.Model):
    """
    Total aggregated stats for campaigns.
    """
    total_priority = models.PositiveSmallIntegerField(default=0)
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


class DirectMailCampaignStats(models.Model):
    """
    Model for Direct Mail Campaign Stats
    """
    total_delivered_pieces = models.PositiveSmallIntegerField(default=0)
    delivery_rate = models.PositiveSmallIntegerField(default=0)
    total_undelivered_pieces = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def get_delivery_rate(self):
        try:
            total_prospect_count = self.dm_campaign.campaign.total_prospects
            delivery_rate = round(
                self.total_delivered_pieces / int(total_prospect_count) * 100,
            )
        except ZeroDivisionError:
            delivery_rate = 0
        return delivery_rate

    @property
    def get_undeliverable_rate(self):
        try:
            total_prospect_count = self.dm_campaign.campaign.total_prospects
            undeliverable = round(
                self.total_undelivered_pieces / int(total_prospect_count) * 100,
            )
        except ZeroDivisionError:
            undeliverable = 0
        return undeliverable

    @property
    def tracking_url(self):
        return self.dm_campaign.order.tracking_url
