from django.db.models import Q, Sum

from core import models


class CampaignManager(models.Manager):
    def has_access(self, user):
        """
        Returns a queryset of campaigns the provided user has access to.

        :param user User: User object to get accessible campaigns.
        """
        from sherpa.models import Campaign

        if user.profile.company and (user.profile.is_admin or user.is_staff):
            # Master admins and admins has access to all campaigns under their company.
            # Sherpa staff has carte blanche access to all campaigns.
            return user.profile.company.campaign_set.all()

        campaign_ids = user.profile.campaignaccess_set.values_list('campaign_id', flat=True)

        # Some sherpa admin users might not always have a company.
        if not user.profile.company:
            return Campaign.objects.none()

        return user.profile.company.campaign_set.filter(id__in=campaign_ids)

    def archive(self, archive=True, *args, **kwargs):
        """
        Used similarly to filter.  Any instances found will be updated to the passed `archived`
        parameter.
        :param archive bool: Value to set `is_archived`.
        """
        queryset = self.filter(*args, **kwargs)
        return queryset.update(is_archived=archive)


class CampaignDailyStatsManager(models.Manager):
    def summary(self, campaign, start_date=None, end_date=None):
        """
        Get the aggregated summary stats for a given campaign in a date range and return a queryset
        with those stats.

        :param campaign Campaign: instance of a campaign that we want summary of.
        :param start_date Date: start date to begin aggregation.
        :param end_date Date: end date to stop aggregation at.
        """
        queryset = self.get_queryset().filter(campaign=campaign)

        date_filter = Q()
        if start_date:
            date_filter &= Q(date__gte=start_date)
        if end_date:
            date_filter &= Q(date__lte=end_date)
        queryset = queryset.filter(date_filter)

        return queryset.aggregate(
            auto_dead=Sum('auto_dead'),
            new_leads=Sum('new_leads'),
            skipped=Sum('skipped'),
            delivered=Sum('delivered'),
            sent=Sum('sent'),
            responses=Sum('responses'),
        )


class DirectMailCampaignManager(models.Manager):
    def create(self, *args, **kwargs):
        """
        Set `Campaign.is_direct_mail` to True when creating DirectMailCampaign
        """
        if 'campaign' in kwargs:
            campaign = kwargs['campaign']
            campaign.is_direct_mail = True
            campaign.save(update_fields=['is_direct_mail'])

        return super(DirectMailCampaignManager, self).create(*args, **kwargs)
