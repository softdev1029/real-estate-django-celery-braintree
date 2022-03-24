import re

from import_export import resources
from import_export.fields import Field

from core.resources import SherpaModelResource
from sherpa.models import Company, InternalDNC


class CompanyResource(resources.ModelResource):
    class Meta:
        model = Company


class DNCResource(SherpaModelResource):
    """
    Do not call CSV resource.  Unions sherpa.InternalDNC and sherpa.Prospect
    """
    phone_raw = Field(attribute='phone_raw', column_name='Phone')

    class Meta:
        model = InternalDNC
        fields = ('phone_raw',)

    def clean_phone_raw(self, data):
        return re.sub(r'\D', '', data)


class CampaignMetaStatsResource(SherpaModelResource):
    campaign = Field(attribute='campaign', column_name='Campaign')
    sent = Field(attribute='sent', column_name='Sent')
    delivered = Field(attribute='delivered', column_name='Delivered')
    responses = Field(attribute='responses', column_name='Responses')
    new_leads = Field(attribute='new_leads', column_name='New Leads')
    auto_dead = Field(attribute='auto_dead', column_name='Auto Dead')
    skipped = Field(attribute='skipped', column_name='Skipped')
    delivery_rate = Field(attribute='delivery_rate', column_name='Delivery Rate')
    response_rate = Field(attribute='response_rate', column_name='Response Rate')
    performance_rating = Field(attribute='performance_rating', column_name='Performance Rating')

    class Meta:
        fields = (
            'campaign',
            'sent',
            'delivered',
            'responses',
            'new_leads',
            'auto_dead',
            'skipped',
            'delivery_rate',
            'response_rate',
            'performance_rating',
        )


class ProfileStatsResource(SherpaModelResource):
    id = Field(attribute='id', column_name='ID')
    name = Field(attribute='name', column_name='Name')
    attempts = Field(attribute='attempts', column_name='Attempts')
    delivered = Field(attribute='delivered', column_name='Delivered')
    leads_created = Field(attribute='leads_created', column_name='Leads Created')
    lead_rate = Field(attribute='lead_rate', column_name='Lead Rate')
    avg_response_time = Field(attribute='avg_response_time', column_name='Average Response Time')

    class Meta:
        fields = (
            'id',
            'name',
            'attempts',
            'delivered',
            'leads_created',
            'lead_rate',
            'avg_response_time',
        )


class PodioResource(SherpaModelResource):
    """
    Defines the fields that can be mapped and exported from sherpa to podio
    """
    first_name = Field(attribute='first_name', column_name='first_name', readonly=True)
    last_name = Field(attribute='last_name', column_name='last_name', readonly=True)
    campaign_name = Field(attribute='get_campaign_name', column_name='campaign_name', readonly=True)
    tags = Field(attribute='prop__tags__name', column_name='tags')
    public_url = Field(attribute='public_url', column_name='public_url')
    sherpa_url = Field(attribute='sherpa_url', column_name='sherpa_url')
    notes = Field(attribute='notes', column_name='notes')
    # property data
    property_address = Field(attribute='prop__address__address', column_name='address_address')
    property_city = Field(attribute='prop__address__city', column_name='address_city')
    property_state = Field(attribute='prop__address__state', column_name='address_state')
    property_zip = Field(attribute='prop__address__zip_code', column_name='address_zip')
    mailing_address = Field(
        attribute='prop__mailing_address__address',
        column_name='mailing_address',
    )
    mailing_city = Field(attribute='prop__mailing_address__city', column_name='mailing_city')
    mailing_state = Field(attribute='prop__mailing_address__state', column_name='mailing_state')
    mailing_zip = Field(attribute='prop__mailing_address__zip_code', column_name='mailing_zip')

    # attom data
    legal_description = Field(
        attribute='prop__address__attom__legal_description',
        column_name='legal_description',
    )
    year_built = Field(attribute='prop__address__attom__year_built', column_name='year_built')
    deed_last_sale_date = Field(
        attribute='prop__address__attom__deed_last_sale_date',
        column_name='deed_last_sale_date',
    )
    deed_last_sale_price = Field(
        attribute='prop__address__attom__deed_last_sale_price',
        column_name='deed_last_sale_price',
    )
    area_gross = Field(attribute='prop__address__attom__area_gross', column_name='area_gross')
    bath_count = Field(attribute='prop__address__attom__bath_count', column_name='bath_count')
    bath_partial_count = Field(
        attribute='prop__address__attom__bath_partial_count',
        column_name='bath_partial_count',
    )
    bedrooms_count = Field(
        attribute='prop__address__attom__bedrooms_count',
        column_name='bedrooms_count',
    )
    cur_first_position_open_loan_amount = Field(
        attribute='prop__address__attom__attomloan__cur_first_position_open_loan_amount',
        column_name='cur_first_position_open_loan_amount',
    )
    available_equity = Field(
        attribute='prop__address__attom__attomloan__available_equity',
        column_name='available_equity',
    )
    quitclaim_flag = Field(attribute='quitclaim_flag')
    transfer_amount = Field(attribute='transfer_amount')
    grantor_1name_first = Field(attribute='grantor_1name_first')
    grantor_1name_last = Field(attribute='grantor_1name_last')

    # data from prospect
    owner_name_1 = Field(attribute='get_full_name', column_name='owner_1_name', readonly=True)
    phone_1 = Field(attribute='phone_raw', column_name='phone_1', readonly=True)
    phone_1_type = Field(attribute='phone_type', column_name='phone_1_type', readonly=True)
    lead_stage_1 = Field(attribute='lead_stage_title', column_name='lead_stage', readonly=True)
    owner_1_verified_status = Field(
        attribute='owner_verified_status',
        column_name='owner_1_verified_status',
        readonly=True,
    )
    custom_1 = Field(attribute='custom1', column_name='custom_1')
    custom_2 = Field(attribute='custom2', column_name='custom_2')
    custom_3 = Field(attribute='custom3', column_name='custom_3')
    custom_4 = Field(attribute='custom4', column_name='custom_4')

    # Remaining values exist in SkipTraceProperty
    validated_mailing_address = Field(
        attribute='skiptrace__validated_mailing_address_lines',
        column_name='validated_mailing_address',
        readonly=True,
    )
    golden_address = Field(
        attribute='skiptrace__golden_address_lines',
        column_name='golden_address',
        readonly=True,
    )

    last_seen_1 = Field(
        attribute='skiptrace__returned_phone_last_seen_1',
        column_name='last_seen',
        readonly=True,
    )
    email_1 = Field(
        attribute='skiptrace__returned_email_1',
        column_name='email_1',
        readonly=True,
    )
    email_1_last_seen = Field(
        attribute='skiptrace__returned_email_last_seen_1',
        column_name='email_1_last_seen',
        readonly=True,
    )
    email_2 = Field(attribute='skiptrace__returned_email_2', column_name='email_2', readonly=True)
    email_2_last_seen = Field(
        attribute='skiptrace__returned_email_last_seen_2',
        column_name='email_2_last_seen',
        readonly=True,
    )
    alt_names = Field(
        attribute='skiptrace__has_alternate_name',
        column_name='alternate_names',
        readonly=True,
    )
    vacancy = Field(
        attribute='skiptrace__validated_property_vacant',
        column_name='vacancy',
        readonly=True,
    )
    ip_addr = Field(
        attribute='skiptrace__returned_ip_address',
        column_name='ip_address',
        readonly=True,
    )
    age = Field(attribute='skiptrace__age', column_name='age', readonly=True)
    is_deceased = Field(attribute='skiptrace__deceased', column_name='is_deceased', readonly=True)
    bankruptcy = Field(attribute='skiptrace__bankruptcy', column_name='bankruptcy', readonly=True)
    foreclosure = Field(
        attribute='skiptrace__returned_foreclosure_date',
        column_name='foreclosure',
        readonly=True,
    )
    lien = Field(attribute='skiptrace__returned_lien_date', column_name='lien', readonly=True)
    judgment = Field(
        attribute='skiptrace__returned_judgment_date',
        column_name='judgment',
        readonly=True,
    )
    rel_1_name = Field(
        attribute='skiptrace__proper_relative_1_full_name',
        column_name='relative_1_name',
        readonly=True,
    )
    rel_1_numbers = Field(
        attribute='skiptrace__relative_1_numbers',
        column_name='relative_1_numbers',
        readonly=True,
    )
    rel_2_name = Field(
        attribute='skiptrace__proper_relative_2_full_name',
        column_name='relative_2_name',
        readonly=True,
    )
    rel_2_numbers = Field(
        attribute='skiptrace__relative_2_numbers',
        column_name='relative_2_numbers',
        readonly=True,
    )
    litigator = Field(
        attribute='skiptrace__has_litigator',
        column_name='litigator',
        readonly=True,
    )
    pushed_to_campaign = Field(
        attribute='skiptrace__in_campaign',
        column_name='pushed_to_campaign',
        readonly=True,
    )
    skip_trace_date = Field(
        attribute='skiptrace__created',
        column_name='skip_trace_date',
        readonly=True,
    )
    agent = Field(attribute='reminder_agent__fullname', column_name='agent', readonly=True)

    def dehydrate_campaign_name(self, obj):
        campaign_name = None
        if obj.campaignprospect_set.count() > 0:
            campaignProspect = obj.campaignprospect_set.first()
            campaign_name = campaignProspect.campaign.name
        return campaign_name

    def dehydrate_tags(self, obj):
        tags = ""
        if obj.prop and obj.prop.tags.count() > 0:
            tags = ", ".join([tag.name for tag in obj.prop.tags.all()])
        return tags

    def dehydrate_notes(self, obj):
        notes = ""
        if obj.note_set.count() > 0:
            notes = "\n".join([notes.text for notes in obj.note_set.all()])
        return notes

    def dehydrate_owner_name_1(self, obj):
        fullname = None
        if obj.first_name and obj.last_name:
            fullname = f'{obj.first_name} {obj.last_name}'
        return fullname

    def _get_attom_recorder_data(self, obj, key, default=None):
        """
        Walks the prospect object down to the attom_recorder model

        :param obj Prospect: The prospect instance currently being exported
        :param key String:   An attribute that belongs to AttomRecorder
        :param default None: Default value we want to return if walking down the object fails
        """
        property_obj = obj.prop
        if property_obj:
            address = property_obj.address
            if address:
                attom = address.attom
                if attom:
                    attom_recorder = attom.attomrecorder_set.first()
                    if attom_recorder:
                        return getattr(attom_recorder, key)
        return default

    def dehydrate_quitclaim_flag(self, obj):
        return self._get_attom_recorder_data(obj, 'quitclaim_flag')

    def dehydrate_transfer_amount(self, obj):
        return self._get_attom_recorder_data(obj, 'transfer_amount')

    def dehydrate_grantor_1name_first(self, obj):
        return self._get_attom_recorder_data(obj, 'grantor_1name_first')

    def dehydrate_grantor_1name_last(self, obj):
        return self._get_attom_recorder_data(obj, 'grantor_1name_last')

    def export_resource(self, obj):
        data = {}
        fields = self.get_export_fields()
        for i, field in enumerate(fields):
            data[field.column_name] = self.export_field(field, obj)
        return data
