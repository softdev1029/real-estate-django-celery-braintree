from import_export.fields import Field
from import_export.resources import ModelResource

from core.resources import SherpaModelResource
from .models import SkipTraceDailyStats, SkipTraceProperty


class SkipTraceResource(SherpaModelResource):
    submitted_owner_fullname = Field(attribute='submitted_owner_fullname', column_name='Full Name')
    submitted_owner_first_name = Field(
        attribute='submitted_owner_first_name',
        column_name='First Name',
    )
    submitted_owner_last_name = Field(
        attribute='submitted_owner_last_name', column_name='Last Name')
    submitted_mailing_address = Field(
        attribute='submitted_mailing_address',
        column_name='Mail Address',
    )
    submitted_mailing_city = Field(attribute='submitted_mailing_city', column_name='Mail City')
    submitted_mailing_state = Field(attribute='submitted_mailing_state', column_name='Mail State')
    submitted_mailing_zip = Field(attribute='submitted_mailing_zip', column_name='Mail Zip')
    submitted_property_address = Field(
        attribute='submitted_property_address',
        column_name='Property Address',
    )
    submitted_property_city = Field(
        attribute='submitted_property_city',
        column_name='Property City',
    )
    submitted_property_state = Field(
        attribute='submitted_property_state',
        column_name='Property State',
    )
    submitted_property_zip = Field(attribute='submitted_property_zip', column_name='Property Zip')
    submitted_custom_1 = Field(attribute='submitted_custom_1', column_name='Custom 1')
    submitted_custom_2 = Field(attribute='submitted_custom_2', column_name='Custom 2')
    submitted_custom_3 = Field(attribute='submitted_custom_3', column_name='Custom 3')
    submitted_custom_4 = Field(attribute='submitted_custom_4', column_name='Custom 4')
    submitted_custom_5 = Field(attribute='submitted_custom_5', column_name='Custom 5')
    submitted_custom_6 = Field(attribute='submitted_custom_6', column_name='Custom 6')
    validated_mailing_address_lines = Field(
        attribute='validated_mailing_address_lines',
        column_name='Validated Mail Address',
    )
    validated_mailing_city_name = Field(
        attribute='validated_mailing_city_name',
        column_name='Validated Mail City',
    )
    validated_mailing_state_abbreviation = Field(
        attribute='validated_mailing_state_abbreviation',
        column_name='Validated Mail State',
    )
    validated_mailing_zipcode = Field(
        attribute='validated_mailing_zipcode',
        column_name='Validated Mail Zip',
    )
    validated_mailing_vacant = Field(attribute='validated_mailing_vacant', column_name='Vacant')
    proper_returned_fullname = Field(
        attribute='proper_returned_fullname',
        column_name='Alternate Full Name',
    )
    proper_returned_first_name = Field(
        attribute='proper_returned_first_name',
        column_name='Alternate First Name',
    )
    proper_returned_last_name = Field(
        attribute='proper_returned_last_name',
        column_name='Alternate Last Name',
    )
    returned_phone_1 = Field(attribute='returned_phone_1', column_name='Phone1')
    returned_phone_type_1 = Field(attribute='returned_phone_type_1', column_name='Phone1 Type')
    returned_phone_last_seen_1 = Field(
        attribute='returned_phone_last_seen_1',
        column_name='Phone1 Last Seen',
    )
    returned_phone_2 = Field(attribute='returned_phone_2', column_name='Phone2')
    returned_phone_type_2 = Field(attribute='returned_phone_type_2', column_name='Phone2 Type')
    returned_phone_last_seen_2 = Field(
        attribute='returned_phone_last_seen_2',
        column_name='Phone2 Last Seen',
    )
    returned_phone_3 = Field(attribute='returned_phone_3', column_name='Phone3')
    returned_phone_type_3 = Field(attribute='returned_phone_type_3', column_name='Phone3 Type')
    returned_phone_last_seen_3 = Field(
        attribute='returned_phone_last_seen_3',
        column_name='Phone3 Last Seen',
    )
    proper_returned_email_1 = Field(attribute='proper_returned_email_1', column_name='Email1')
    returned_email_last_seen_1 = Field(
        attribute='returned_email_last_seen_1',
        column_name='Email1 Last Seen',
    )
    proper_returned_email_2 = Field(attribute='proper_returned_email_2', column_name='Email2')
    returned_email_last_seen_2 = Field(
        attribute='returned_email_last_seen_2',
        column_name='Email2 Last Seen',
    )
    returned_ip_address = Field(attribute='returned_ip_address', column_name='IP Address')
    returned_ip_last_seen = Field(attribute='returned_ip_last_seen', column_name='IP Last Seen')
    golden_address_lines = Field(attribute='golden_address_lines', column_name='Golden Address')
    golden_city = Field(attribute='golden_city', column_name='Golden City')
    golden_state = Field(attribute='golden_state', column_name='Golden State')
    golden_zipcode = Field(attribute='golden_zipcode', column_name='Golden Zip')
    golden_last_seen = Field(attribute='golden_last_seen', column_name='Golden Address Last Seen')
    age = Field(attribute='age', column_name='Age')
    is_deceased = Field(attribute='is_deceased', column_name='Is Deceased')
    bankruptcy = Field(attribute='bankruptcy', column_name='Bankruptcy')
    returned_foreclosure_date = Field(
        attribute='returned_foreclosure_date',
        column_name='Foreclosure',
    )
    returned_lien_date = Field(attribute='returned_lien_date', column_name='Lien')
    returned_judgment_date = Field(attribute='returned_judgment_date', column_name='Judgment')
    quitclaim_flag = Field(attribute='get_quitclaim_flag', column_name='Quitclaim')
    available_equity = Field(attribute='get_available_equity', column_name='Available Equity')
    proper_relative_1_first_name = Field(
        attribute='proper_relative_1_first_name',
        column_name='Relative 1 First Name',
    )
    proper_relative_1_last_name = Field(
        attribute='proper_relative_1_last_name',
        column_name='Relative 1 Last Name',
    )
    relative_1_phone1 = Field(attribute='relative_1_phone1', column_name='Relative 1 Phone1')
    relative_1_phone2 = Field(attribute='relative_1_phone2', column_name='Relative 1 Phone2')
    relative_1_phone3 = Field(attribute='relative_1_phone3', column_name='Relative 1 Phone3')
    proper_relative_2_first_name = Field(
        attribute='proper_relative_2_first_name',
        column_name='Relative 2 First Name',
    )
    proper_relative_2_last_name = Field(
        attribute='proper_relative_2_last_name',
        column_name='Relative 2 Last Name',
    )
    relative_2_phone1 = Field(attribute='relative_2_phone1', column_name='Relative 2 Phone1')
    relative_2_phone2 = Field(attribute='relative_2_phone2', column_name='Relative 2 Phone2')
    relative_2_phone3 = Field(attribute='relative_2_phone3', column_name='Relative 2 Phone3')
    has_litigator = Field(attribute='has_litigator', column_name='Litigator')
    has_hit = Field(attribute='has_hit', column_name='Has Hit')
    record_status = Field(attribute='record_status', column_name='Record Status')

    def dehydrate_is_deceased(self, obj):
        """
        Format as 'Yes', 'No' or blank for export. Boolean value is a 'True' or 'False' string here.
        """
        if not obj.deceased:
            return ''
        if obj.deceased == 'True':
            return 'Yes'
        return 'No'

    class Meta:
        model = SkipTraceProperty
        fields = (
            'submitted_owner_fullname',
            'submitted_owner_first_name',
            'submitted_owner_last_name',
            'submitted_mailing_address',
            'submitted_mailing_city',
            'submitted_mailing_state',
            'submitted_mailing_zip',
            'submitted_property_address',
            'submitted_property_city',
            'submitted_property_state',
            'submitted_property_zip',
            'submitted_custom_1',
            'submitted_custom_2',
            'submitted_custom_3',
            'submitted_custom_4',
            'submitted_custom_5',
            'submitted_custom_6',
            'validated_mailing_address_lines',
            'validated_mailing_city_name',
            'validated_mailing_state_abbreviation',
            'validated_mailing_zipcode',
            'validated_mailing_vacant',
            'proper_returned_fullname',
            'proper_returned_first_name',
            'proper_returned_last_name',
            'returned_phone_1',
            'returned_phone_type_1',
            'returned_phone_last_seen_1',
            'returned_phone_2',
            'returned_phone_type_2',
            'returned_phone_last_seen_2',
            'returned_phone_3',
            'returned_phone_type_3',
            'returned_phone_last_seen_3',
            'proper_returned_email_1',
            'returned_email_last_seen_1',
            'proper_returned_email_2',
            'returned_email_last_seen_2',
            'returned_ip_address',
            'returned_ip_last_seen',
            'golden_address_lines',
            'golden_city',
            'golden_state',
            'golden_zipcode',
            'golden_last_seen',
            'age',
            'is_deceased',
            'bankrputcy',
            'returned_foreclosure_date',
            'returned_lien_date',
            'returned_judgment_date',
            'quitclaim_flag',
            'available_equity',
            'proper_relative_1_first_name',
            'proper_relative_1_last_name',
            'relative_1_phone1',
            'relative_1_phone2',
            'relative_1_phone3',
            'proper_relative_2_first_name',
            'proper_relative_2_last_name',
            'relative_2_phone1',
            'relative_2_phone2',
            'relative_2_phone3',
            'has_litigator',
            'has_hit',
            'record_status',
        )


class SkipTraceDailyStatsResource(ModelResource):
    class Meta:
        model = SkipTraceDailyStats
        fields = ('date', 'total_internal_hits', 'total_external_hits')
