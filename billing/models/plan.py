from core import models


class PublicPlanManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_public=True)


class Plan(models.Model):
    """
    Data about the plans we have available in braintree.

    There are more possible plans listed in braintree, but we also have a set of standard plans that
    are used for general users. This allows us to change plans through Sherpa and modify their
    application data according. It will also give us a way to make plan data available for signup
    and change through data provided through the API.
    """
    braintree_id = models.CharField(max_length=16)
    max_monthly_prospect_count = models.PositiveIntegerField()
    first_market_phone_number_count = models.PositiveSmallIntegerField()

    # Only certain plans are available for choosing signup or change.
    is_public = models.BooleanField(default=False)

    public = PublicPlanManager()
    objects = models.Manager()

    def __str__(self):
        return self.braintree_id
