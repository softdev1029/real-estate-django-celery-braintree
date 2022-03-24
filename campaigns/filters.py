from django_filters.rest_framework import FilterSet, RangeFilter

from django.db.models import Q

from sherpa.models import Campaign


class CampaignFilter(FilterSet):
    percent_complete = RangeFilter(
        field_name='percent_complete',
        method='filter_percent_complete',
    )

    class Meta:
        model = Campaign
        fields = (
            'owner', 'market', 'is_archived', 'is_direct_mail',
            'is_followup', 'percent_complete', 'has_unread_sms',
        )

    def filter_percent_complete(self, queryset, name, value):
        """
        Filters campaign using URL params `percent_complete_min` and `percent_complete_max`.
        They respectfully default to 0 and 100 if either is not sent in the request.
        """
        min_percent = value.start or 0
        max_percent = value.stop or 100
        return queryset.filter(Q(percent__gte=min_percent, percent__lte=max_percent))
