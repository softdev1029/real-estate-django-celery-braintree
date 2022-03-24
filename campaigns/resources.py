from import_export.fields import Field
import pytz

from core.resources import SherpaModelResource
from sherpa.models import Campaign


class CampaignResource(SherpaModelResource):
    name = Field(attribute='name', column_name='Name')
    market = Field(attribute='market', column_name='Market')
    owner = Field(column_name='Owner')
    created_date = Field(column_name='Created Date')
    progress = Field(column_name='Progress')
    health = Field(attribute='health', column_name='Health')
    is_archived = Field(attribute='is_archived', column_name='Archived')
    is_followup = Field(attribute='is_followup', column_name='Followup')
    total_priority = Field(
        attribute='campaign_stats__total_priority',
        column_name='Total Priority',
    )
    total_prospects = Field(attribute='total_prospects', column_name='Total Prospects')
    total_sms_followups = Field(
        attribute='campaign_stats__total_sms_followups',
        column_name='Total SMS Followup',
    )
    total_skipped = Field(attribute='campaign_stats__total_skipped', column_name='Total Skipped')
    total_dnc_count = Field(
        attribute='campaign_stats__total_dnc_count',
        column_name='Total DNC Count',
    )
    total_sms_sent_count = Field(
        attribute='campaign_stats__total_sms_sent_count',
        column_name='Total SMS Sent Count',
    )
    total_sms_received_count = Field(
        attribute='campaign_stats__total_sms_received_count',
        column_name='Total SMS Received Count',
    )
    total_auto_dead_count = Field(
        attribute='campaign_stats__total_auto_dead_count',
        column_name='Total Auto Dead Count',
    )
    total_initial_sent_skipped = Field(
        attribute='campaign_stats__total_initial_sent_skipped',
        column_name='Total Initial Sent Skipped',
    )
    total_mobile = Field(attribute='campaign_stats__total_mobile', column_name='Total Mobile')
    total_landline = Field(
        attribute='campaign_stats__total_landline',
        column_name='Total Landline',
    )
    total_phone_other = Field(
        attribute='campaign_stats__total_phone_other',
        column_name='Total Phone Other',
    )
    total_leads = Field(attribute='campaign_stats__total_leads', column_name='Total Leads')
    call_forward_number = Field(attribute='call_forward_number', column_name='Forwarding Number')
    timezone = Field(attribute='timezone', column_name='Timezone')
    skip_prospects_who_messaged = Field(
        attribute='skip_prospects_who_messaged', column_name='Skip Prospects Who Messaged')

    class Meta:
        model = Campaign
        fields = (
            'name',
            'market',
            'owner',
            'created_date',
            'health',
            'is_archived',
            'is_followup',
            'total_priority',
            'total_prospects',
            'total_sms_followups',
            'total_skipped',
            'total_dnc_count',
            'total_sms_sent_count',
            'total_sms_received_count',
            'total_auto_dead_count',
            'total_initial_sent_skipped',
            'total_mobile',
            'total_landline',
            'total_phone_other',
            'total_leads',
            'call_forward_number',
            'timezone',
            'skip_prospects_who_messaged',
        )

    def dehydrate_tags(self, campaign):
        return ', '.join(list(campaign.tags.values_list('name', flat=True)))

    def dehydrate_owner(self, campaign):
        if campaign.owner:
            return campaign.owner.user.get_full_name()
        return None

    def dehydrate_created_date(self, campaign):
        timezone = campaign.company.timezone
        created_date = campaign.created_date.astimezone(pytz.timezone(timezone))
        return created_date.strftime("%c")

    def dehydrate_progress(self, campaign):
        return campaign.percent_complete
