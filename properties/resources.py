from import_export.fields import Field

from core.resources import SherpaModelResource
from .models import Property


class PropertyResource(SherpaModelResource):
    """
    Property csv resource.
    """
    property_address = Field(attribute='address__address', column_name='Property Street')
    property_city = Field(attribute='address__city', column_name='Property City')
    property_state = Field(attribute='address__state', column_name='Property State')
    property_zip = Field(attribute='address__zip_code', column_name='Property Zip')
    mailing_address = Field(attribute='mailing_address__address', column_name='Mailing Street')
    mailing_city = Field(attribute='mailing_address__city', column_name='Mailing City')
    mailing_state = Field(attribute='mailing_address__state', column_name='Mailing State')
    mailing_zip = Field(attribute='mailing_address__zip_code', column_name='Mailing Zipcode')
    # Prospect 1 - 7
    custom_1 = Field(attribute='custom1', column_name='Custom 1')
    custom_2 = Field(attribute='custom2', column_name='Custom 2')
    custom_3 = Field(attribute='custom3', column_name='Custom 3')
    custom_4 = Field(attribute='custom4', column_name='Custom 4')
    owner_first_name_1 = Field(attribute='first_name', column_name='Owner 1 First name')
    owner_last_name_1 = Field(attribute='last_name', column_name='Owner 1 Last name')
    phone_1 = Field(attribute='phone_raw', column_name='Phone 1')
    phone_1_type = Field(attribute='phone_type', column_name='Phone Type')
    lead_stage_1 = Field(attribute='lead_stage_title', column_name='Lead Stage')
    last_seen_1 = Field(attribute='last_sms_received_utc', column_name='Last Seen')
    owner_1_verified_status = Field(
        attribute='verified_status', column_name='Owner 1 Verified Status')
    # Prospect 2 - 18
    owner_first_name_2 = Field(attribute='first_name', column_name='Owner 2 First name')
    owner_last_name_2 = Field(attribute='last_name', column_name='Owner 2 Last name')
    phone_2 = Field(attribute='phone_raw', column_name='Phone 2')
    phone_2_type = Field(attribute='phone_type', column_name='Phone Type')
    lead_stage_2 = Field(attribute='lead_stage_title', column_name='Lead Stage')
    last_seen_2 = Field(attribute='last_sms_received_utc', column_name='Last Seen')
    owner_2_verified_status = Field(
        attribute='verified_status', column_name='Owner 2 Verified Status')
    # Prospect 3 - 25
    owner_first_name_3 = Field(attribute='first_name', column_name='Owner 3 First name')
    owner_last_name_3 = Field(attribute='last_name', column_name='Owner 3 Last name')
    phone_3 = Field(attribute='phone_raw', column_name='Phone 3')
    phone_3_type = Field(attribute='phone_type', column_name='Phone Type')
    lead_stage_3 = Field(attribute='lead_stage_title', column_name='Lead Stage')
    last_seen_3 = Field(attribute='last_sms_received_utc', column_name='Last Seen')
    owner_3_verified_status = Field(
        attribute='verified_status', column_name='Owner 3 Verified Status')
    # Skip trace - 32
    validated_mailing_address = Field(
        attribute='validated_mailing_address_lines', column_name='Validated mailing address')
    golden_address = Field(attribute='golden_address_lines', column_name='Golden address')
    email_1 = Field(attribute='returned_email_1', column_name='Email 1')
    email_1_last_seen = Field(attribute='returned_email_last_seen_1', column_name='Last seen')
    email_2 = Field(attribute='returned_email_2', column_name='Email 2')
    email_2_last_seen = Field(attribute='returned_email_last_seen_2', column_name='Last seen')
    alt_names = Field(attribute='has_alternate_name', column_name='Alternate names')
    vacancy = Field(attribute='validated_property_vacant', column_name='Vacancy')
    ip_addr = Field(attribute='returned_ip_address', column_name='IP address')
    age = Field(attribute='age', column_name='Age')
    is_deceased = Field(attribute='deceased', column_name='Is deceased')
    bankruptcy = Field(attribute='bankruptcy', column_name='Bankruptcy')
    foreclosure = Field(attribute='returned_foreclosure_date', column_name='Foreclosure')
    lien = Field(attribute='returned_lien_date', column_name='Lien')
    judgement = Field(attribute='returned_judgment_date', column_name='Judgment')
    rel_1_first_name = Field(
        attribute='proper_relative_1_first_name',
        column_name='Relative 1 First name',
    )
    rel_1_last_name = Field(
        attribute='proper_relative_1_last_name',
        column_name='Relative 1 Last name',
    )
    rel_1_phone1 = Field(attribute='relative_1_phone1', column_name='Relative 1 Phone 1')
    rel_1_phone2 = Field(attribute='relative_1_phone2', column_name='Relative 1 Phone 2')
    rel_1_phone3 = Field(attribute='relative_1_phone3', column_name='Relative 1 Phone 3')
    rel_2_first_name = Field(
        attribute='proper_relative_2_first_name',
        column_name='Relative 2 First name',
    )
    rel_2_last_name = Field(
        attribute='proper_relative_2_last_name',
        column_name='Relative 2 Last name',
    )
    rel_2_phone1 = Field(attribute='relative_2_phone1', column_name='Relative 2 Phone 1')
    rel_2_phone2 = Field(attribute='relative_2_phone2', column_name='Relative 2 Phone 2')
    rel_2_phone3 = Field(attribute='relative_2_phone3', column_name='Relative 2 Phone 3')
    litigator = Field(attribute='has_litigator', column_name='Litigator')
    pushed_to_campaign = Field(attribute='in_campaign', column_name='Pushed to campaign')
    skip_trace_date = Field(attribute='created', column_name='Skip traced date')

    class Meta:
        model = Property
        fields = (
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'mailing_address',
            'mailing_city',
            'mailing_state',
            'mailing_zip',
            'validated_mailing_address',
            'golden_address',
            'custom_1',
            'custom_2',
            'custom_3',
            'custom_4',
            'custom_5',
            'custom_6',
            'owner_first_name_1',
            'owner_last_name_1',
            'phone_1',
            'phone_1_type',
            'lead_stage_1',
            'last_seen_1',
            'owner_1_verified_status',
            'owner_first_name_2',
            'owner_last_name_2',
            'phone_2',
            'phone_2_type',
            'lead_stage_2',
            'last_seen_2',
            'owner_2_verified_status',
            'owner_first_name_3',
            'owner_last_name_3',
            'phone_3',
            'phone_3_type',
            'lead_stage_3',
            'last_seen_3',
            'owner_3_verified_status',
            'email_1',
            'email_1_last_seen',
            'email_2',
            'email_2_last_seen',
            'alt_names',
            'vacancy',
            'ip_addr',
            'age',
            'is_deceased',
            'bankruptcy',
            'foreclosure',
            'lien',
            'judgement',
            'rel_1_first_name',
            'rel_1_last_name',
            'rel_1_phone1',
            'rel_1_phone2',
            'rel_1_phone3',
            'rel_2_first_name',
            'rel_2_last_name',
            'rel_2_phone1',
            'rel_2_phone2',
            'rel_2_phone3',
            'litigator',
            'pushed_to_campaign',
            'skip_trace_date',
        )

    def export_resource(self, obj):
        data = []
        fields = self.get_export_fields()
        prospects = obj.prospect_set.all()
        [prospect_1, prospect_2, prospect_3] = [*prospects[:3], *[None] * (3 - len(prospects[:3]))]
        skip_trace = obj.skiptraceproperty_set.first()
        for i, field in enumerate(fields):
            lookup = obj
            if i > 7:
                lookup = prospect_1
                if i > 18:
                    lookup = prospect_2
                if i > 25:
                    lookup = prospect_3
                if i > 32:
                    lookup = skip_trace
            if not lookup:
                data.append('')
            else:
                data.append(self.export_field(field, lookup))
        return data
