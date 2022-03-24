from django.contrib.postgres.fields import ArrayField

from core import models
from sherpa.abstracts import AbstractNote, AbstractTag


class CampaignIssue(models.Model):
    """
    There are some common issues that come up with campaigns that users should be aware about and
    should have general suggestions to overcome them.
    """
    code = models.CharField(max_length=16, unique=True)
    issue_desc = models.CharField(max_length=255)
    suggestions = ArrayField(models.CharField(max_length=128), default=list)

    def __str__(self):
        return self.code


class CampaignTag(AbstractTag):
    """
    Tags that a company has for labeling and grouping campaigns.
    """
    pass


class CampaignNote(AbstractNote):
    """
    Notes about a campaign.
    """
    campaign = models.ForeignKey('sherpa.Campaign', on_delete=models.CASCADE, related_name='notes')

    def __str__(self):
        return self.text[:30]


class InitialResponse(models.Model):
    """
    Track messages that are the first response from a prospect on a campaign.

    We could add some fields onto `SMSMessage` to properly track which messages were the first
    responses on a campaign, however splitting these messages out into their own model has some
    advantages:

    1) Easily get the first message from prospects in a campaign, without querying `SMSMessage`
    2) Determine response rates filtered by datetime
    3) Track meta statistics about first received, such as auto-dead or auto-priority (future)

    This model will also allow us to get rid of the `has_responded_via_sms` fields on `Prospect` and
    `CampaignProspect`.
    """
    created = models.DateTimeField(auto_now_add=True)
    campaign = models.ForeignKey('sherpa.Campaign', on_delete=models.CASCADE)
    message = models.ForeignKey('sherpa.SMSMessage', on_delete=models.CASCADE)
    is_auto_dead = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        """
        Need to check that the same prospect can't be saved twice for an initial response on the
        same campaign.

        Ideally we do this with a database constraint, however we'd need to duplicate the prospect
        from the sms message.
        """
        if self.pk is None:
            # Creating a new record.
            prospect = self.message.prospect
            queryset = InitialResponse.objects.filter(
                message__prospect=prospect,
                campaign=self.campaign,
            )
            if queryset.exists():
                raise Exception(f'Initial response already exists for prospect {prospect.id} on '
                                f'campaign {self.campaign.name}.')

        super(InitialResponse, self).save(*args, **kwargs)

    def __str__(self):
        return f'{self.message.prospect.get_full_name()} in {self.campaign.name}'

    class Meta:
        unique_together = ['campaign', 'message']
