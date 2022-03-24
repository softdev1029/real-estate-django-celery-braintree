from django.utils.functional import cached_property

from core import models
from core.utils import clean_phone
from .uploadskiptrace import UploadSkipTrace


class SkipTraceProperty(models.Model):
    """
    Record created when a user uploads to skip trace.

    Skip trace search data from IDI is saved back to class.
    """
    upload_skip_trace = models.ForeignKey(
        UploadSkipTrace, null=True, blank=True, on_delete=models.CASCADE)
    # Deprecated. Use company on UploadSkiptraceProperty instead
    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.CASCADE)

    prop = models.ForeignKey('properties.Property', blank=True, null=True, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True)
    skip_trace_status = models.CharField(null=True, blank=True, max_length=255)
    is_existing_match = models.BooleanField(default=False)
    synced_push_to_campaign = models.BooleanField(default=False)
    has_hit = models.BooleanField(default=False)
    existing_match_prospect_id = models.CharField(null=True, blank=True, max_length=16)
    matching_prospect_id_1 = models.IntegerField(default=0)
    matching_prospect_id_2 = models.IntegerField(default=0)
    matching_prospect_id_3 = models.IntegerField(default=0)
    submitted_owner_fullname = models.CharField(null=True, blank=True, max_length=255)
    submitted_owner_first_name = models.CharField(null=True, blank=True, max_length=255)
    submitted_owner_last_name = models.CharField(null=True, blank=True, max_length=255)
    submitted_property_address = models.CharField(null=True, blank=True, max_length=255)
    submitted_property_city = models.CharField(null=True, blank=True, max_length=255)
    submitted_property_state = models.CharField(null=True, blank=True, max_length=255)
    submitted_property_zip = models.CharField(null=True, blank=True, max_length=255)
    submitted_mailing_address = models.CharField(null=True, blank=True, max_length=255)
    submitted_mailing_city = models.CharField(null=True, blank=True, max_length=255)
    submitted_mailing_state = models.CharField(null=True, blank=True, max_length=255)
    submitted_mailing_zip = models.CharField(null=True, blank=True, max_length=255)
    submitted_custom_1 = models.CharField(null=True, blank=True, max_length=512)
    submitted_custom_2 = models.CharField(null=True, blank=True, max_length=512)
    submitted_custom_3 = models.CharField(null=True, blank=True, max_length=512)
    submitted_custom_4 = models.CharField(null=True, blank=True, max_length=512)
    submitted_custom_5 = models.CharField(null=True, blank=True, max_length=512)
    submitted_custom_6 = models.CharField(null=True, blank=True, max_length=512)

    returned_fullname = models.CharField(null=True, blank=True, max_length=255)
    returned_first_name = models.CharField(null=True, blank=True, max_length=255)
    returned_last_name = models.CharField(null=True, blank=True, max_length=255)
    returned_phone_1 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_2 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_3 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_4 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_5 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_type_1 = models.CharField(null=True, blank=True, max_length=64)
    returned_phone_type_2 = models.CharField(null=True, blank=True, max_length=64)
    returned_phone_type_3 = models.CharField(null=True, blank=True, max_length=64)
    returned_phone_type_4 = models.CharField(null=True, blank=True, max_length=64)
    returned_phone_type_5 = models.CharField(null=True, blank=True, max_length=64)
    returned_phone_is_disconnected_1 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_is_disconnected_2 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_is_disconnected_3 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_is_disconnected_4 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_is_disconnected_5 = models.CharField(null=True, blank=True, max_length=16)
    returned_phone_carrier_1 = models.CharField(null=True, blank=True, max_length=128)
    returned_phone_carrier_2 = models.CharField(null=True, blank=True, max_length=128)
    returned_phone_carrier_3 = models.CharField(null=True, blank=True, max_length=128)
    returned_phone_carrier_4 = models.CharField(null=True, blank=True, max_length=128)
    returned_phone_carrier_5 = models.CharField(null=True, blank=True, max_length=128)
    returned_phone_last_seen_1 = models.DateField(null=True, blank=True)
    returned_phone_last_seen_2 = models.DateField(null=True, blank=True)
    returned_phone_last_seen_3 = models.DateField(null=True, blank=True)
    returned_phone_last_seen_4 = models.DateField(null=True, blank=True)
    returned_phone_last_seen_5 = models.DateField(null=True, blank=True)
    returned_email_1 = models.CharField(null=True, blank=True, max_length=125)
    returned_email_2 = models.CharField(null=True, blank=True, max_length=125)
    returned_email_3 = models.CharField(null=True, blank=True, max_length=125)
    returned_email_last_seen_1 = models.DateField(null=True, blank=True)
    returned_email_last_seen_2 = models.DateField(null=True, blank=True)
    returned_email_last_seen_3 = models.DateField(null=True, blank=True)
    returned_address_1 = models.CharField(null=True, blank=True, max_length=255)
    returned_city_1 = models.CharField(null=True, blank=True, max_length=255)
    returned_state_1 = models.CharField(null=True, blank=True, max_length=255)
    returned_zip_1 = models.CharField(null=True, blank=True, max_length=255)
    returned_address_last_seen_1 = models.DateField(null=True, blank=True)
    returned_address_2 = models.CharField(null=True, blank=True, max_length=255)
    returned_city_2 = models.CharField(null=True, blank=True, max_length=255)
    returned_state_2 = models.CharField(null=True, blank=True, max_length=255)
    returned_zip_2 = models.CharField(null=True, blank=True, max_length=255)
    returned_address_last_seen_2 = models.DateField(null=True, blank=True)
    returned_ip_address = models.GenericIPAddressField(null=True, blank=True)
    returned_ip_last_seen = models.DateField(null=True, blank=True)
    returned_foreclosure_date = models.DateField(null=True, blank=True)
    returned_lien_date = models.DateField(null=True, blank=True)
    returned_judgment_date = models.DateField(null=True, blank=True)
    validated_returned_address_1 = models.CharField(null=True, blank=True, max_length=255)
    validated_returned_address_2 = models.CharField(null=True, blank=True, max_length=255)
    validated_returned_city_1 = models.CharField(null=True, blank=True, max_length=255)
    validated_returned_state_1 = models.CharField(null=True, blank=True, max_length=255)
    validated_returned_zip_1 = models.CharField(null=True, blank=True, max_length=255)
    validated_returned_property_status = models.CharField(null=True, blank=True, max_length=16)

    validated_property_status = models.CharField(
        null=True, blank=True, max_length=16, db_index=True)
    validated_property_delivery_line_1 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_property_delivery_line_2 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_property_last_line = models.CharField(null=True, blank=True, max_length=255)
    validated_property_primary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_street_predirection = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_postdirection = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_suffix = models.CharField(null=True, blank=True, max_length=16)
    validated_property_secondary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_property_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_extra_secondary_number = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_extra_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_pmb_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_property_pmb_number = models.CharField(null=True, blank=True, max_length=255)
    validated_property_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_default_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_state_abbreviation = models.CharField(null=True, blank=True, max_length=255)
    validated_property_zipcode = models.CharField(null=True, blank=True, max_length=16)
    validated_property_plus4_code = models.CharField(null=True, blank=True, max_length=16)
    validated_property_latitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_longitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_precision = models.CharField(null=True, blank=True, max_length=255)
    validated_property_time_zone = models.CharField(null=True, blank=True, max_length=255)
    validated_property_utc_offset = models.CharField(null=True, blank=True, max_length=16)
    validated_property_vacant = models.CharField(null=True, blank=True, max_length=16)

    validated_mailing_status = models.CharField(null=True, blank=True, max_length=16, db_index=True)
    validated_mailing_delivery_line_1 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_mailing_delivery_line_2 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_mailing_last_line = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_primary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_street_predirection = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_postdirection = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_suffix = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_secondary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_secondary_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_extra_secondary_number = models.CharField(
        null=True, blank=True, max_length=255)
    validated_mailing_extra_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_mailing_pmb_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_pmb_number = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_default_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_state_abbreviation = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_zipcode = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_plus4_code = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_latitude = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_longitude = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_precision = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_time_zone = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_utc_offset = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_vacant = models.CharField(null=True, blank=True, max_length=16)

    age = models.CharField(null=True, blank=True, max_length=255)
    # Deprecated use age instead
    date_of_birth = models.CharField(null=True, blank=True, max_length=255)
    age = models.IntegerField(null=True, blank=True)
    deceased = models.CharField(null=True, blank=True, max_length=255)
    bankruptcy = models.CharField(null=True, blank=True, max_length=255)
    relative_1_first_name = models.CharField(null=True, blank=True, max_length=255)
    relative_1_last_name = models.CharField(null=True, blank=True, max_length=255)
    relative_1_phone1 = models.CharField(null=True, blank=True, max_length=255)
    relative_1_phone2 = models.CharField(null=True, blank=True, max_length=255)
    relative_1_phone3 = models.CharField(null=True, blank=True, max_length=255)
    relative_2_first_name = models.CharField(null=True, blank=True, max_length=255)
    relative_2_last_name = models.CharField(null=True, blank=True, max_length=255)
    relative_2_phone1 = models.CharField(null=True, blank=True, max_length=255)
    relative_2_phone2 = models.CharField(null=True, blank=True, max_length=255)
    relative_2_phone3 = models.CharField(null=True, blank=True, max_length=255)

    upload_error = models.TextField(null=True, blank=True)

    @property
    def is_entity(self):
        """
        Return whether this is an entity (based on name).
        """
        name = f"{self.submitted_owner_fullname} {self.submitted_owner_first_name} " \
               f"{self.submitted_owner_last_name}"
        if name:
            return set(name.lower().split()) & {'llc', 'trust', 'corp', 'estate'}
        return False

    @property
    def has_alternate_name(self):
        """
        Return whether there's an alternate name.
        """
        return any([self.returned_fullname, self.returned_first_name, self.returned_last_name])

    @property
    def no_hit_calculated(self):
        if self.returned_phone_1 or self.returned_email_1 or self.returned_address_1:
            return 'YES Hit'
        else:
            return 'NO Hit'

    @property
    def phone_list(self):
        """
        Return list of phone numbers.
        """
        phone_list = []

        if self.returned_phone_1:
            phone_raw = self.returned_phone_1
            phone_clean = clean_phone(phone_raw)
            if phone_clean:
                phone_list.append(phone_clean)

        if self.returned_phone_2:
            phone_raw2 = self.returned_phone_2
            phone_clean2 = clean_phone(phone_raw2)
            if phone_clean2:
                phone_list.append(phone_clean2)

        if self.returned_phone_3:
            phone_raw3 = self.returned_phone_3
            phone_clean3 = clean_phone(phone_raw3)
            if phone_clean3:
                phone_list.append(phone_clean3)

        return phone_list

    @cached_property
    def first_three_property_prospects(self):
        """
        Return list of up to three prospects based on property.
        """
        prospects = self.prop.prospect_set.all()[:3] if self.prop else []
        return [prospect for prospect in prospects]

    @property
    def has_litigator(self):
        """
        Return Boolean indicating if this `SkipTraceProperty` has a litigator.
        """
        from sherpa.models import LitigatorList
        has_litigator_list = False
        for ph in self.phone_list:
            has_litigator_list = LitigatorList.objects.filter(phone=ph).exists()
            if has_litigator_list:
                break
        return has_litigator_list

    @property
    def blank_name(self):
        """
        Return whether or not name is blank.
        """
        return not self.submitted_owner_first_name and not self.submitted_owner_last_name

    def address_validated(self, is_property_address=False):
        """
        Check if there's a valid address.
        """
        if is_property_address and self.validated_property_status == 'validated' and \
                self.validated_property_delivery_line_1 and self.validated_property_zipcode:
            return True
        if not is_property_address and self.validated_mailing_status == 'validated' and \
                self.validated_mailing_delivery_line_1 and self.validated_mailing_zipcode:
            return True
        return False

    @property
    def has_mailing_submitted(self):
        return self.submitted_mailing_address and self.submitted_mailing_zip

    @property
    def has_returned_address_validated(self):
        return self.validated_returned_property_status == 'validated' and \
            self.validated_returned_address_1 and self.validated_returned_zip_1

    @property
    def has_returned_address(self):
        return self.returned_address_1 and self.returned_zip_1

    # These properties are used for the export process.  The data that will be added to the
    # exported file must be presented in a proper format.
    @property
    def proper_returned_fullname(self):
        return self.__proper_field('returned_fullname')

    @property
    def proper_returned_first_name(self):
        return self.__proper_field('returned_first_name')

    @property
    def proper_returned_last_name(self):
        return self.__proper_field('returned_last_name')

    def get_nth_prospect_attr(self, n, name):
        if n > len(self.first_three_property_prospects):
            return
        prospect = self.first_three_property_prospects[n - 1]
        attr = getattr(prospect, name)
        return attr() if callable(attr) else attr

    @property
    def prospect_1_name(self):
        return self.get_nth_prospect_attr(1, 'get_full_name')

    @property
    def prospect_1_lead_stage(self):
        return self.get_nth_prospect_attr(1, 'lead_stage_title')

    @property
    def prospect_1_verified_status(self):
        return self.get_nth_prospect_attr(1, 'owner_verified_status')

    @property
    def prospect_2_name(self):
        return self.get_nth_prospect_attr(2, 'get_full_name')

    @property
    def prospect_2_lead_stage(self):
        return self.get_nth_prospect_attr(2, 'lead_stage_title')

    @property
    def prospect_2_verified_status(self):
        return self.get_nth_prospect_attr(2, 'owner_verified_status')

    @property
    def prospect_3_name(self):
        return self.get_nth_prospect_attr(3, 'get_full_name')

    @property
    def prospect_3_lead_stage(self):
        return self.get_nth_prospect_attr(3, 'lead_stage_title')

    @property
    def prospect_3_verified_status(self):
        return self.get_nth_prospect_attr(3, 'owner_verified_status')

    @property
    def in_campaign(self):
        prospects = self.first_three_property_prospects
        return any([p.campaign_qs.exists() for p in prospects])

    @property
    def in_dm_campaign(self):
        prospects = self.first_three_property_prospects
        if not prospects:
            return
        for p in prospects:
            if p.campaign_qs.filter(directmail__isnull=False).exists():
                return True
        return False

    @property
    def proper_relative_1_first_name(self):
        return self.__proper_field('relative_1_first_name')

    @property
    def proper_relative_1_last_name(self):
        return self.__proper_field('relative_1_last_name')

    @property
    def proper_relative_1_full_name(self):
        return f'{self.proper_relative_1_first_name} {self.proper_relative_1_last_name}'

    @property
    def relative_1_numbers(self):
        return ', '.join(filter(None, [
            self.relative_1_phone1, self.relative_1_phone2, self.relative_1_phone3]))

    @property
    def proper_relative_2_first_name(self):
        return self.__proper_field('relative_2_first_name')

    @property
    def proper_relative_2_last_name(self):
        return self.__proper_field('relative_2_last_name')

    @property
    def proper_relative_2_full_name(self):
        return f'{self.proper_relative_2_first_name} {self.proper_relative_2_last_name}'

    @property
    def relative_2_numbers(self):
        return ', '.join(filter(None, [
            self.relative_2_phone1, self.relative_2_phone2, self.relative_2_phone3]))

    @property
    def validated_returned_address_lines(self):
        return_line = ''
        if self.validated_returned_address_2:
            return_line = self.validated_returned_address_2

        return f'{ self.validated_returned_address_1 } { return_line }'

    @property
    def validated_mailing_address_lines(self):
        mailing_line = ''
        if self.validated_mailing_delivery_line_2:
            mailing_line = self.validated_mailing_delivery_line_2

        return f'{ self.validated_mailing_delivery_line_1 } { mailing_line }'

    @property
    def proper_returned_email_1(self):
        email = self.returned_email_1
        if not email:
            return ''
        return email.lower()

    @property
    def proper_returned_email_2(self):
        email = self.returned_email_2
        if not email:
            return ''
        return email.lower()

    @property
    def record_status(self):
        if not self.has_hit:
            return ''

        status = 'new'
        if self.is_existing_match:
            status = 'existing'
        return status

    @property
    def golden_address_lines(self):
        address_lines = self.full_golden_address[0]
        if not address_lines:
            return ''
        return address_lines.title()

    @property
    def golden_city(self):
        city = self.full_golden_address[1]
        if not city:
            return ''
        return city.title()

    @property
    def golden_state(self):
        state = self.full_golden_address[2]
        if not state:
            return ''
        return state.upper()

    @property
    def golden_zipcode(self):
        return self.full_golden_address[3]

    @property
    def golden_last_seen(self):
        return self.full_golden_address[4]

    @property
    def get_quitclaim_flag(self):
        if self.prop:
            return self.prop.get_quitclaim_flag

    @property
    def get_available_equity(self):
        if self.prop:
            return self.prop.get_available_equity

    @cached_property
    def full_golden_address(self):
        address = ''
        city = ''
        state = ''
        zipcode = ''
        address_last_seen = ''

        if not (self.has_returned_address and self.has_mailing_submitted):
            return [address, city, state, zipcode, address_last_seen]

        returned_prefix = 'returned_'
        mailing_prefix = 'submitted_mailing_'
        address_suffix = 'address'
        zipcode_suffix = 'zip'

        if self.has_returned_address_validated:
            returned_prefix = 'validated_returned_'

        if self.address_validated():
            mailing_prefix = 'validated_mailing_'
            address_suffix = 'delivery_line_1'
            zipcode_suffix = 'zipcode'

        mailing_address = getattr(self, f'{ mailing_prefix }{ address_suffix }')
        mailing_zip = getattr(self, f'{ mailing_prefix }{ zipcode_suffix }')
        returned_address = getattr(self, f'{ returned_prefix }address_1')
        returned_city = getattr(self, f'{ returned_prefix }city_1')
        returned_state = getattr(self, f'{ returned_prefix }state_1')
        returned_zip = getattr(self, f'{ returned_prefix }zip_1')

        if mailing_address != returned_address and mailing_zip != returned_zip:
            address = returned_address
            if self.has_returned_address_validated:
                address = self.validated_returned_address_lines
            city = returned_city
            state = returned_state
            zipcode = returned_zip
            address_last_seen = self.returned_address_last_seen_1

        return [address, city, state, zipcode, address_last_seen]

    def get_full_name(self):
        """
        Return the property's full name.

        This should be used instead of "fullname" which will be removed as a database field. Instead
        of using f-strings here, we need to take into account that first_name or last_name might be
        None (i.e. in the case of LLC).
        """
        full_name = str(self.submitted_owner_first_name or '') + ' ' + str(
            self.submitted_owner_last_name or '')
        return full_name.strip()

    def __proper_field(self, field):
        value = getattr(self, field)
        return value.title() if value else ''

    def create_property(self):
        """
        Create `Property` from `SkipTraceProperty`
        """
        from properties.utils import get_or_create_address
        from properties.models import Property, PropertyTagAssignment

        addresses = self.__get_address_for_property_creation()
        property_address_obj = get_or_create_address(addresses['property'])
        if property_address_obj:
            # Now that we have the property and mailing address, we can create the property.
            prop, _ = Property.objects.get_or_create(
                company=self.upload_skip_trace.company,
                address=property_address_obj,
                defaults={
                    'mailing_address': get_or_create_address(addresses['mailing']),
                },
            )
            property_tag_ids = self.upload_skip_trace.property_tags.values_list('pk', flat=True)
            if property_tag_ids:
                # TODO: After Django 3+ upgrade, any author reviewing this section to test and
                # revert this.
                # https://github.com/django/django/blob/3.0.11/django/db/models/fields/related_descriptors.py#L1129
                PropertyTagAssignment.objects.bulk_create(
                    [
                        PropertyTagAssignment(prop_id=prop.id, tag_id=tag_id)
                        for tag_id in property_tag_ids
                    ],
                    ignore_conflicts=True,
                )
            self.prop = prop
            self.save(update_fields=['prop'])

    def __get_address_for_property_creation(self):
        # Fields to use to create `Address` for `Property` object.
        address_fields = {
            'street': ['delivery_line_1', 'address'],
            'city': ['city_name', 'city'],
            'state': ['state_abbreviation', 'state'],
            'zip': ['zipcode', 'zip'],
        }
        address_types = ['property', 'mailing']
        addresses = {'property': dict(), 'mailing': dict()}
        for address_type in address_types:
            validated = getattr(self, f'validated_{address_type}_status') == 'validated'
            prefix = 'validated_' if validated else 'submitted_'
            index = 0 if validated else 1
            for key in address_fields.keys():
                field = f'{prefix}{address_type}_{address_fields[key][index]}'
                addresses[address_type][key] = getattr(self, field)

        return addresses

    def get_data_from_skip_trace_property(self):
        """
        Get `SkipTraceProperty` data to save to `Prospect`.
        """
        data = self.__get_name_and_email_for_prospect()
        data.update(self.__get_address_for_prospect())

        # Add custom fields
        for i in range(1, 5):
            data[f'custom{i}'] = getattr(self, f'submitted_custom_{i}')

        return data

    def __get_name_and_email_for_prospect(self):
        """
        Get name and email from `SkipTraceProperty` to save to `Prospect`.
        """
        data = {}
        prefix = 'submitted_owner'
        if self.is_entity and self.has_alternate_name:
            prefix = 'returned'

        first_name = getattr(self, f'{prefix}_first_name')
        last_name = getattr(self, f'{prefix}_last_name')
        data['first_name'] = first_name.title() if first_name else ''
        data['last_name'] = last_name.title() if last_name else ''

        if self.returned_email_1:
            data['email'] = self.returned_email_1
        return data

    def __get_address_for_prospect(self):
        """
        Get address data from `SkipTraceProperty` to save to `Prospect`.
        """
        data = {}

        address_types = ['property', 'mailing']
        for address_type in address_types:
            if not self.prop or (address_type == 'mailing' and not self.prop.mailing_address):
                prefix = f'{address_type}_'
                address = getattr(self, f'submitted_{prefix}address')
                city = getattr(self, f'submitted_{prefix}city')
                state = getattr(self, f'submitted_{prefix}state')
                data = {
                    f'{prefix}address': address.title() if address else '',
                    f'{prefix}city': city.title() if city else '',
                    f'{prefix}state': state,
                    f'{prefix}zip': getattr(self, f'submitted_{prefix}zip'),
                }

        if self.address_validated(is_property_address=True):
            validated_fields = [
                'vacant',
                'status',
                'delivery_line_1',
                'delivery_line_2',
                'plus4_code',
                'latitude',
                'longitude',
            ]
            prefix = 'validated_property_'
            for field in validated_fields:
                key = f'{prefix}{field}'
                data[key] = getattr(self, key)

        return data

    def save_from_single_upload_form(self, form_data, user):
        """
        Save `SkipTraceProperty` from Single Skip Trace Upload Form.

        form_data must include Boolean `property_only`and have at least the following:
        `property_address`, `property_city`, `property_atate`, `property_zip`
        If `property_only` is false, must also include:
        `first_name`, 'last_name`, `mailing_address`, `mailing_city`, `mailing_state`,
        `mailing_zip`

        Note: A request sent through django rest framework that originally has camel case
        formatting gets converted to the format expected here. For example if the user posts data
        with 'propertyOnly', what django rest framework sends here will be 'property_only'
        """
        if 'property_only' not in form_data:
            return None, 'Must include property only'
        address_types = ['property']
        address_fields = ['address', 'city', 'state', 'zip']
        update_fields = []
        if not form_data.get('property_only', False):
            first_name = form_data.get('first_name', '')
            last_name = form_data.get('last_name', '')
            if not (first_name or last_name):
                return None, 'Must include name'
            self.submitted_owner_first_name = first_name
            self.submitted_owner_last_name = last_name
            self.submitted_owner_fullname = f'{first_name} {last_name}'
            update_fields = [
                'submitted_owner_fullname',
                'submitted_owner_first_name',
                'submitted_owner_last_name',
            ]
            address_types.append('mailing')

        field_mapping = dict()
        for address_type in address_types:
            for field in address_fields:
                form_field_name = f'{address_type}_{field}'
                if form_field_name not in form_data:
                    return None, 'Must include all address fields'
                update_field = f'submitted_{address_type}_{field}'
                update_fields.append(update_field)
                field_mapping[update_field] = form_data.get(form_field_name)

        self.upload_skip_trace = \
            UploadSkipTrace.create_new(user, total_rows=1, has_header=False)
        update_fields.extend(['upload_skip_trace'])

        for update_field in field_mapping:
            setattr(self, update_field, field_mapping[update_field])
        self.save()
        return self, None

    def copy_mailing_address(self):
        """
        Copy property address to mailing address.
        """
        address_schema = {
            'submitted': ['address', 'city', 'state', 'zip'],
            'validated': ['status',
                          'delivery_line_1',
                          'delivery_line_2',
                          'last_line',
                          'primary_number',
                          'street_name',
                          'street_predirection',
                          'street_postdirection',
                          'street_suffix',
                          'secondary_number',
                          'secondary_designator',
                          'extra_secondary_number',
                          'extra_secondary_designator',
                          'pmb_designator',
                          'pmb_number',
                          'city_name',
                          'default_city_name',
                          'state_abbreviation',
                          'zipcode',
                          'plus4_code',
                          'latitude',
                          'longitude',
                          'precision',
                          'time_zone',
                          'utc_offset',
                          'vacant',
                          ],
        }
        update_fields = []
        for address_type in address_schema:
            for field in address_schema[address_type]:
                update_field = f'{address_type}_mailing_{field}'
                update_fields.append(update_field)
                value = getattr(self, f'{address_type}_property_{field}')
                setattr(self, update_field, value)

        self.save(update_fields=update_fields)

    def copy_address_from_prospect(self, prospect, is_skip_trace=False):
        """
        Copy mailing address from `Prospect` or `SkipTraceProperty`.
        """
        address_fields = ['address', 'city', 'state', 'zip']
        update_fields = []
        for field in address_fields:
            update_field = f'submitted_mailing_{field}'
            update_fields.append(update_field)
            if is_skip_trace:
                from_field = update_field
            else:
                from_field = f'mailing_{field}'
            value = getattr(prospect, from_field)
            setattr(self, update_field, value)
        self.save(update_fields=update_fields)

    def copy_name_from_prospect(self, prospect, is_skip_trace=False):
        """
        Copy name from `Prospect`, or `SkipTraceProperty` if indicated.
        """
        name_fields = ['fullname', 'first_name', 'last_name']
        update_fields = []
        for field in name_fields:
            update_field = f'submitted_owner_{field}'
            update_fields.append(update_field)
            if is_skip_trace:
                from_field = update_field
            else:
                from_field = field

            if from_field == 'fullname':
                # Full name should use the prospect's method instead of db field.
                value = prospect.get_full_name()
            else:
                value = getattr(prospect, from_field)
            setattr(self, update_field, value)
        self.save(update_fields=update_fields)

    def copy_relative_data(self, match):
        """
        Copy relative data from another 'SkipTraceProperty'.
        """
        fields = ['first_name', 'last_name', 'phone1', 'phone2', 'phone3']
        update_fields = []

        for relative_index in range(1, 3):
            for field in fields:
                update_field = f'relative_{relative_index}_{field}'
                update_fields.append(update_field)
                setattr(self, update_field, getattr(match, update_field))

        self.save(update_fields=update_fields)

    class Meta:
        app_label = 'sherpa'
        ordering = ['pk']
        verbose_name_plural = 'skip trace properties'
