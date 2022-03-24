from django_filters import BooleanFilter, FilterSet, ModelChoiceFilter

from sherpa.models import CampaignProspect, LeadStage


class CampaignProspectFilter(FilterSet):
    """
    Custom filters for the prospect model.

    We use this to remove the `prospect__*` prefix when filtering on prospect fields, making the
    frontend implementation cleaner.
    """
    is_qualified_lead = BooleanFilter(field_name="prospect__is_qualified_lead")
    lead_stage = ModelChoiceFilter(
        field_name="prospect__lead_stage",
        queryset=LeadStage.objects.all(),
    )
    dead_auto_unviewed = BooleanFilter(method='get_dead_auto_unviewed')

    def get_dead_auto_unviewed(self, queryset, name, value):
        user = self.request.user
        dead_lead = LeadStage.objects.get(
            company=user.profile.company,
            lead_stage_title='Dead (Auto)',
        )
        return queryset.filter(prospect__lead_stage=dead_lead, has_been_viewed=False)

    class Meta:
        model = CampaignProspect
        fields = ('lead_stage', 'campaign', 'is_qualified_lead', 'dead_auto_unviewed')
