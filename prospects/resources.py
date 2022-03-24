from import_export.fields import Field

from core.resources import SherpaModelResource
from sherpa.models import CampaignProspect, Prospect


class ProspectResource(SherpaModelResource):
    fullname = Field(attribute='get_full_name', column_name='Full Name')
    first_name = Field(attribute='first_name', column_name='First Name')
    last_name = Field(attribute='last_name', column_name='Last Name')
    lead_stage_title = Field(attribute='lead_stage_title', column_name='Stage')
    phone_display = Field(attribute='phone_display', column_name='Phone')
    email = Field(attribute='email', column_name='Email')
    mailing_address = Field(attribute='mailing_address', column_name='Mailing Street')
    mailing_city = Field(attribute='mailing_city', column_name='Mailing City')
    mailing_state = Field(attribute='mailing_state', column_name='Mailing State')
    mailing_zip = Field(attribute='mailing_zip', column_name='Mailing Zipcode')
    property_address = Field(attribute='property_address', column_name='Property Street')
    property_city = Field(attribute='property_city', column_name='Property City')
    property_state = Field(attribute='property_state', column_name='Property State')
    property_zip = Field(attribute='property_zip', column_name='Property Zip')
    phone_type = Field(attribute='phone_type', column_name='Phone Type')
    tags = Field(column_name='Tags')
    custom1 = Field(attribute='custom1', column_name='Custom 1')
    custom2 = Field(attribute='custom2', column_name='Custom 2')
    custom3 = Field(attribute='custom3', column_name='Custom 3')
    custom4 = Field(attribute='custom4', column_name='Custom 4')
    created_date = Field(attribute='created_date', column_name='First Import Date')
    last_import_date = Field(attribute='last_import_date', column_name='Last Import Date')
    owner_verified_status = Field(attribute='owner_verified_status', column_name='Owner Verified')
    validated_property_vacant = Field(
        attribute='validated_property_vacant',
        column_name='Is Vacant',
    )
    campaign_names = Field(attribute='campaign_names', column_name='Campaigns')
    do_not_call = Field(attribute='do_not_call', column_name='DNC')
    wrong_number = Field(attribute='wrong_number', column_name='Wrong Number')
    last_sms_sent_local = Field(attribute='last_sms_sent_local', column_name='Last SMS Sent')
    last_sms_received_local = Field(
        attribute='last_sms_received_local',
        column_name='Last SMS Received',
    )
    sherpa_url = Field(attribute='sherpa_url', column_name='Sherpa Page')
    public_url = Field(attribute='public_url', column_name='Public Page')

    class Meta:
        model = Prospect
        fields = (
            'fullname',
            'first_name',
            'last_name',
            'lead_stage_title',
            'phone_display',
            'email',
            'mailing_address',
            'mailing_city',
            'mailing_state',
            'mailing_zip',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'phone_type',
            'tags',
            'custom1',
            'custom2',
            'custom3',
            'custom4',
            'created_date',
            'last_import_date',
            'owner_verified_status',
            'validated_property_vacant',
            'campaign_names',
            'do_not_call',
            'wrong_number',
            'last_sms_sent_local',
            'last_sms_received_local',
            'sherpa_url',
            'public_url',
        )

    def dehydrate_tags(self, prospect):
        if not prospect.prop:
            return ''
        return ', '.join(list(prospect.prop.tags.values_list('name', flat=True)))


class CampaignProspectResource(SherpaModelResource):
    full_name = Field(attribute='prospect__get_full_name', column_name='Full Name')
    first_name = Field(attribute='prospect__first_name', column_name='First Name')
    last_name = Field(attribute='prospect__last_name', column_name='Last Name')
    stage = Field(attribute='prospect__lead_stage_title', column_name='Stage')
    phone = Field(attribute='prospect__phone_display', column_name='Phone')
    email = Field(attribute='prospect__email', column_name='Email')
    mailing_street = Field(attribute='prospect__mailing_address', column_name='Mailing Street')
    mailing_city = Field(attribute='prospect__mailing_city', column_name='Mailing City')
    mailing_state = Field(attribute='prospect__mailing_state', column_name='Mailing State')
    mailing_zip = Field(attribute='prospect__mailing_zip', column_name='Mailing Zipcode')
    property_street = Field(attribute='prospect__property_address', column_name='Property Street')
    property_city = Field(attribute='prospect__property_city', column_name='Property City')
    property_state = Field(attribute='prospect__property_state', column_name='Property State')
    property_zip = Field(attribute='prospect__property_zip', column_name='Property Zip')
    phone_type = Field(attribute='prospect__phone_type', column_name='Phone Type')
    tags = Field(column_name='Tags')
    custom_1 = Field(attribute='prospect__custom1', column_name='Custom 1')
    custom_2 = Field(attribute='prospect__custom2', column_name='Custom 2')
    custom_3 = Field(attribute='prospect__custom3', column_name='Custom 3')
    custom_4 = Field(attribute='prospect__custom4', column_name='Custom 4')
    first_import_date = Field(attribute='prospect__created_date', column_name='First Import Date')
    last_import_date = Field(attribute='prospect__last_import_date', column_name='Last Import Date')
    owner_verified = Field(
        attribute='prospect__owner_verified_status',
        column_name='Owner Verified',
    )
    is_vacant = Field(attribute='prospect__validated_property_vacant', column_name='Is Vacant')
    campaign_names = Field(attribute='prospect__campaign_names', column_name='Campaigns')
    dnc = Field(attribute='prospect__do_not_call', column_name='DNC')
    wrong_number = Field(attribute='prospect__wrong_number', column_name='Wrong Number')
    last_sms_sent = Field(attribute='prospect__last_sms_sent_local', column_name='Last SMS Sent')
    last_sms_received = Field(
        attribute='prospect__last_sms_received_local',
        column_name='Last SMS Received',
    )
    sherpa_page = Field(attribute='prospect__sherpa_url', column_name='Sherpa Page')
    public_page = Field(attribute='prospect__public_url', column_name='Public Page')
    skip_reason = Field(attribute='skip_reason', column_name='Skip Reason')
    litigator = Field(attribute='is_litigator', column_name='Litigator')
    associated_litigator = Field(
        attribute='is_associated_litigator',
        column_name='Associated Litigator',
    )
    last_email_sent = Field(
        attribute='last_email_sent', column_name='Last Mail Sent')
    total_mailings_sent = Field(
        attribute='total_mailings_sent', column_name='Total Mailings Sent')
    last_outbound_call = Field(
        attribute='last_outbound_call', column_name='Last outbound call')
    last_inbound_call = Field(
        attribute='last_inbound_call', column_name='Last Inbound Call')
    notes = Field(
        attribute='public_sms_url', column_name='Notes')

    class Meta:
        model = CampaignProspect
        fields = (
            'first_name',
            'last_name',
            'stage',
            'phone',
            'email',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zip',
            'property_street',
            'property_city',
            'property_state ',
            'property_zip',
            'phone_type',
            'tags',
            'custom_1',
            'custom_2',
            'custom_3',
            'custom_4',
            'first_import_date',
            'last_import_date',
            'owner_verified ',
            'is_vacant',
            'campaign_names ',
            'dnc',
            'wrong_number',
            'last_sms_sent',
            'last_sms_received',
            'sherpa_page',
            'public_page',
            'skip_reason',
            'litigator',
            'associated_litigator',
            'last_email_sent',
            'total_mailings_sent',
            'last_inbound_call',
            'last_outbound_call',
            'notes',
        )

    def dehydrate_tags(self, campaignprospect):
        if not campaignprospect.prospect.prop:
            return ''
        return ', '.join(list(campaignprospect.prospect.prop.tags.values_list('name', flat=True)))
