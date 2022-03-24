import re

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import CharField, Count, F, Q, Value
from django.db.models.functions import Concat
from django.urls import reverse

from core.utils import clean_phone
from properties.utils import get_or_create_attom_tags
from prospects.tasks import upload_prospects_task2
from search.tasks import stacker_full_update
from sherpa.csv_uploader import ProcessUpload
from sherpa.models import CampaignProspect, PhoneNumber, Prospect
from sherpa.utils import convert_to_company_local

# Default headers for exporting prospects & campaign prospects.
PROSPECT_EXPORT_HEADERS = [
    'Full Name', 'First Name', 'Last Name', 'Stage', 'Phone', 'Mailing Street', 'Mailing City',
    'Mailing State', 'Mailing Zipcode', 'Property Street', 'Property City', 'Property State',
    'Property Zipcode', 'Phone Type', 'Custom 1', 'Custom 2', 'Custom 3', 'Custom 4',
    'First Import Date', 'Last Import Date', 'Owner Verified', 'Is Vacant', 'Campaigns', 'DNC',
    'Last SMS Sent', 'Last SMS Received', 'Sherpa Page', 'Public Page']
CP_EXPORT_HEADERS = PROSPECT_EXPORT_HEADERS + ['Skip Reason', 'Litigator', 'Associated Litigator']


class ProspectSearch:
    """
    Search for matching `Prospects` given text to search, and a `LeadStage`.
    """

    def __init__(self, search_input_text, user, params, legacy=False):
        """
        :param search_input_text: string to search fields for
        :param user: `User` that requested this search
        :param params: Query parameters - to be used to build filters.
        :param legacy: Boolean to indicate if this is legacy - to be deprecated.
        """
        self.search_input_text = search_input_text
        self.user = user
        self.params = params
        self.custom_filters = dict()
        self.custom_filter_all_mode = False
        self.is_phone = False
        self.result = None
        self.result_json = None
        self.matches = []
        self.search_all = False
        self.lead_stages_filter = None

    def search(self):
        """
        Clean input data, update `UserProfile` and run search.
        """
        self.__clean_input()
        self.__execute_search()

    def __clean_input(self):
        """
        Clean up input.
        """
        # Check if this is a phone number
        is_phone_number = clean_phone(self.search_input_text)
        if is_phone_number:
            self.search_input_text = is_phone_number
            self.is_phone = True

        # Check if this should be search_all
        if self.search_input_text == '*':
            self.search_input_text = ''
            self.search_all = True

    def __execute_search(self):
        """
        Execute search by filter or search directly for matches if this is a phone.
        """
        if self.is_phone:
            self.result = Prospect.objects.filter(
                phone_raw=self.search_input_text,
                company=self.user.profile.company,
            )
        else:
            self.__execute_search_by_filter()

        self.__filter_by_custom_options()

    def __execute_search_by_filter(self):
        """
        Determine which filter to use, then execute search.
        """
        # Build filters, this can vary based on what's in 'search_input_text'
        search_filter, input_has_number = self.__build_filters()

        # Execute search with chosen filter
        self.result = Prospect.objects.filter(company=self.user.profile.company)
        if not input_has_number:
            self.result = self.result.annotate(
                fn_search=Concat(
                    'first_name',
                    Value(' '),
                    'last_name',
                    output_field=CharField(),
                ),
            )
        self.result = self.result.filter(search_filter)

    def __filter_by_custom_options(self):
        """
        Add filter by other options users selected. Logic will change when any/all toggle is added.
        """
        self.__build_custom_search_filters()
        if self.custom_filters:
            self.result = self.result.filter(**self.custom_filters).distinct()

        if self.custom_filter_all_mode and 'prop__tags__in' in self.custom_filters:
            self.result = self.result.annotate(num_tags=Count('prop__tags')).filter(
                num_tags=len(self.custom_filters['prop__tags__in']),
            )

    def __build_filters(self):
        """
        Build filters for search based on what's in `search_text_input`.
        """
        self.__build_lead_stage_filter()
        # If there's a number we will only search fields that could have numbers.
        input_has_number = bool(re.search(r'\d', self.search_input_text))

        # Phone and address fields that have numbers in them
        number_fields_criteria = (
            Q(phone_raw__icontains=self.search_input_text) | Q(
                property_address__icontains=self.search_input_text) | Q(
                property_zip__icontains=self.search_input_text)
        )
        # All phone and address fields including ones without numbers
        all_phone_and_address_criteria = (
            number_fields_criteria | Q(property_city__icontains=self.search_input_text) | Q(
                property_state__icontains=self.search_input_text)
        )

        # Search only number phone and address fields if there's numbers in search input.
        phone_and_address_criteria = number_fields_criteria \
            if input_has_number else all_phone_and_address_criteria

        # Only search name if there's no numbers in search input
        # Search full name by `fn_search`, an annotation of the concatenation of `first_name` and
        # `last_name`.
        extended_search_criteria = phone_and_address_criteria if input_has_number else (
            Q(fn_search__icontains=self.search_input_text) | phone_and_address_criteria)

        # Build search filters
        basic_search_criteria = Q(company=self.user.profile.company)

        full_search_criteria = basic_search_criteria & extended_search_criteria

        # Determine which filter to used based on 'lead_stage' and 'search_input_text'
        search_filter = basic_search_criteria if self.search_all else full_search_criteria

        if self.lead_stage_filter:
            search_filter = search_filter & self.lead_stage_filter

        return search_filter, input_has_number

    def __build_lead_stage_filter(self):
        """
        Create lead stage filter (also includes priority & qualified lead filters).
        """
        is_priority = self.params.get('is_priority') == 'true'
        is_qualified_lead = self.params.get('is_qualified_lead') == 'true'
        lead_stage = self.params.get('lead_stage')

        # Build lead stage filter
        lead_stage_filter = None
        if lead_stage:
            lead_stage_filter = Q(lead_stage__in=lead_stage.split(','))
        if is_priority:
            priority_filter = Q(is_priority=True)
            lead_stage_filter = \
                priority_filter if not lead_stage_filter else lead_stage_filter | priority_filter
        if is_qualified_lead:
            qualified_filter = Q(is_qualified_lead=True)
            lead_stage_filter = \
                qualified_filter if not lead_stage_filter else lead_stage_filter | qualified_filter

        self.lead_stage_filter = lead_stage_filter

    def __build_custom_search_filters(self):
        """
        Build custom search filters from parameters passed.
        """
        tag = self.params.get('tag')
        self.custom_filter_all_mode = self.params.get('alltags') == 'true'
        verification = self.params.get('verification')
        if tag:
            self.custom_filters['prop__tags__in'] = tag.split(",")
        if verification:
            self.custom_filters['owner_verified_status'] = verification


class ProspectExport:
    """
    Handle exporting of prospects and campaign prospects.
    """
    prospect_headers = PROSPECT_EXPORT_HEADERS
    cp_headers = CP_EXPORT_HEADERS

    def __init__(self, queryset):
        """
        :arg queryset: Queryset instance of prospects or campaign prospects.
        """
        self.export_model = queryset.model
        self.queryset = queryset

    @property
    def export_headers(self):
        """
        Return a list of extra headers to export.

        :param extra: list of extra headers to use if there are more than the default.
        :param remove: list of extra headers to remove from the default list.
        """
        if self.export_model == Prospect:
            export_headers = self.default_prospect_headers
        elif self.export_model == CampaignProspect:
            export_headers = self.default_cp_headers
        else:
            raise Exception(f'Unknown model `{self.export_model}` for `ProspectExport` queryset.')

        return export_headers

    @property
    def prospect_data(self):
        """
        Return a dictionary of data for campaign prospects to be returned in csv export files.
        """
        for prospect in self.queryset.iterator():
            campaign_prospect = prospect.campaignprospect_set.first()
            # Build up a concatenated string of campaign names.
            name_list = [c.name for c in prospect.campaign_qs]
            campaign_names = ', '.join(name_list)

            # Convert datetimes to be local.
            last_sent = convert_to_company_local(prospect.last_sms_sent_utc, prospect.company)
            last_received = convert_to_company_local(
                prospect.last_sms_received_utc, prospect.company)

            # Url that gives the public data of the prospect conversation.
            public_sms_url = reverse('public_sms_stream', kwargs={
                'prospect_token': prospect.token,
                'campaign_id': campaign_prospect.campaign.id,
            })

            # Append all the base data for the prospect and campaign prospect.
            yield {
                'Full Name': prospect.get_full_name(),
                'First Name': prospect.first_name,
                'Last Name': prospect.last_name,
                'Stage': prospect.lead_stage_title,
                'Phone': prospect.phone_display,
                'Mailing Street': prospect.mailing_address,
                'Mailing City': prospect.mailing_city,
                'Mailing State': prospect.mailing_state,
                'Mailing Zipcode': prospect.mailing_zip,
                'Property Street': prospect.property_address,
                'Property City': prospect.property_city,
                'Property State': prospect.property_state,
                'Property Zipcode': prospect.property_zip,
                'Phone Type': prospect.phone_type,
                'Custom 1': prospect.custom1,
                'Custom 2': prospect.custom2,
                'Custom 3': prospect.custom3,
                'Custom 4': prospect.custom4,
                'First Import Date': prospect.created_date,
                'Last Import Date': prospect.campaignprospect_set.last().created_date,
                'Owner Verified': prospect.owner_verified_status,
                'Is Vacant': prospect.validated_property_vacant,
                'Campaigns': campaign_names,
                'DNC': prospect.do_not_call,
                'Last SMS Sent': last_sent,
                'Last SMS Received': last_received,
                'Sherpa Page': settings.APP_URL + prospect.get_absolute_url(),
                'Public Page': settings.APP_URL + public_sms_url,
            }

    @property
    def cp_data(self):
        """
        Return a dictionary of data for campaign prospects to be returned in csv export files.
        """
        self.queryset = self.queryset.annotate(
            campaign_names=ArrayAgg(F('prospect__campaigns__name')),
        )
        for campaign_prospect in self.queryset.iterator():
            prospect = campaign_prospect.prospect
            campaign = campaign_prospect.campaign
            campaign_names = ', '.join(list(filter(None.__ne__, campaign_prospect.campaign_names)))

            # Convert datetimes to be local.
            last_sent = convert_to_company_local(prospect.last_sms_sent_utc, prospect.company)
            last_received = convert_to_company_local(
                prospect.last_sms_received_utc, prospect.company)

            # Url that gives the public data of the prospect conversation.
            public_sms_url = reverse('public_sms_stream', kwargs={
                'prospect_token': prospect.token,
                'campaign_id': campaign.id,
            })

            # Append all the base data for the prospect and campaign prospect.
            yield {
                'Full Name': prospect.get_full_name(),
                'First Name': prospect.first_name,
                'Last Name': prospect.last_name,
                'Stage': prospect.lead_stage_title,
                'Phone': prospect.phone_display,
                'Mailing Street': prospect.mailing_address,
                'Mailing City': prospect.mailing_city,
                'Mailing State': prospect.mailing_state,
                'Mailing Zipcode': prospect.mailing_zip,
                'Property Street': prospect.property_address,
                'Property City': prospect.property_city,
                'Property State': prospect.property_state,
                'Property Zipcode': prospect.property_zip,
                'Phone Type': prospect.phone_type,
                'Custom 1': prospect.custom1,
                'Custom 2': prospect.custom2,
                'Custom 3': prospect.custom3,
                'Custom 4': prospect.custom4,
                'First Import Date': prospect.created_date,
                'Last Import Date': prospect.campaignprospect_set.last().created_date,
                'Owner Verified': prospect.owner_verified_status,
                'Is Vacant': prospect.validated_property_vacant,
                'Campaigns': campaign_names,
                'DNC': prospect.do_not_call,
                'Last SMS Sent': last_sent,
                'Last SMS Received': last_received,
                'Sherpa Page': settings.APP_URL + prospect.get_absolute_url(),
                'Public Page': settings.APP_URL + public_sms_url,
                'Skip Reason': campaign_prospect.skip_reason,
                'Litigator': campaign_prospect.is_litigator,
                'Assocated Litigator': campaign_prospect.is_associated_litigator,
            }


def attempt_auto_verify(prospect):
    """
    When `auto_verify` is turned on a prospect may automatically be verified
    if at least two prospects have the same first and last name and property
    address and at least 66%+ are already verified.
    """
    counts = Prospect.objects.filter(
        phone_raw=prospect.phone_raw,
        first_name=prospect.first_name,
        last_name=prospect.last_name,
        property_address=prospect.property_address,
    ).exclude(
        pk=prospect.pk,
    ).values('owner_verified_status').annotate(
        count=Count('owner_verified_status'),
    ).distinct().order_by()

    total = 0
    verified = 0
    for count in counts:
        total += count['count']
        if count['owner_verified_status'] == 'verified':
            verified = count['count']

    if total >= 2 and verified / total >= 0.66:
        prospect.toggle_owner_verified(None, Prospect.OwnerVerifiedStatus.VERIFIED)


def is_empty_search(params):
    """
    Determine if the user has searched for all prospects without any filters.

    :return bool:
    """
    return all([
        params.get('lead_stage') == '',
        params.get('tag') == '',
        params.get('search') == '',
        params.get('is_priority') == 'false',
        params.get('is_qualified_lead') == 'false',
    ])


def record_phone_number_opt_outs(prospect_phone_number, sherpa_phone_number):
    """
    Aggregates a field on the phone record of total opt outs and marks the prospect as opted
    out.

    This is a util instead of model method because it marks all prospects with that phone number as
    opted out.

    :param prospect_phone_number: raw phone of the prospect that has opted out.
    :param sherpa_phone_number: raw phone of the phone number object that received the optout.
    :return: integer of the count of prospects that were updated to opted out.
    """
    phone_record = PhoneNumber.objects.filter(
        phone=sherpa_phone_number,
        status=PhoneNumber.Status.ACTIVE,
    ).first()
    if not phone_record:
        # The phone number that received the message does not exist.
        return

    # Add to total count
    phone_record.total_opt_outs = phone_record.total_opt_outs + 1
    phone_record.save(update_fields=['total_opt_outs'])

    # Mark all the prospects with this phone number as opted out, we can't message them anymore.
    return Prospect.objects.filter(phone_raw=prospect_phone_number).update(opted_out=True)


def update_stacker_for_upload(upload):
    """
    Update Stacker for a given upload
    """
    prop_id_list = set()
    pros_id_list = set()
    for id in list(upload.property_set.values('id', 'prospect__id')):
        prop_id_list.add(id['id'])
        if id['prospect__id']:
            pros_id_list.add(id['prospect__id'])

    stacker_full_update.delay(list(pros_id_list), list(prop_id_list))


class ProcessProspectUpload(ProcessUpload):
    """
    Save data from `UploadProspect` whether from csv or single skip trace upload.
    """
    def __init__(self, upload, tags=None):
        super().__init__(upload, upload_type='prospect')
        self.tags = tags or []
        self.is_property_upload = not upload.campaign

    def requeue_task(self):
        upload_prospects_task2.delay(self.upload.pk, self.tags)

    def complete_upload(self):
        """
        If upload was successful, set status as complete, charge, and send confirmation email.
        """
        from .tasks import send_upload_email_confirmation_task

        if self.success:
            super().complete_upload()
            if self.upload.campaign and not self.upload.campaign.is_direct_mail:
                if not self.is_property_upload:
                    self.upload.charge()
            send_upload_email_confirmation_task(self.upload.id)

        update_stacker_for_upload(self.upload)

        # Force campaign recalculation.
        if self.upload.campaign:
            self.upload.campaign.update_campaign_stats()

            if self.upload.campaign.is_direct_mail:
                dmc = self.upload.campaign.directmail
                dmc.attempt_auth_and_lock()

    def process_record_from_csv_row(self, row):
        """
        Process record from csv.
        """
        try:
            prop = self.__get_or_create_property_from_row(row)
            data = self.__get_prospect_data_from_row(row)
            phones = self.__get_phone_list_from_row(row)

            # TODO Need to add ore conditions to understand there will not be any phone numbers.
            if not phones:
                Prospect.objects.create_from_data(data, self.upload, prop)
            elif not self.is_property_upload or (data or phones or prop.mailing_address):
                Prospect.objects.create_from_phones(phones, data, self.upload, prop)

            address_obj = prop.address
            if address_obj:
                fetched_tags = get_or_create_attom_tags(address_obj, self.upload.company)
                self.tags.extend(fetched_tags)

            # Attach Property tags to prospect prop.
            if self.tags and prop:
                prop.tags.add(*self.tags)
        except Exception as e:
            # Our customers sometimes miss a value in a column or put the entire address into a
            # single column, both resulting in an exception being raised.
            self.set_error(e)

    def __get_or_create_property_from_row(self, row):
        """
        Get or create `Property` from row passed.
        """
        from properties.models import Property
        from properties.utils import get_or_create_address

        addresses = {}
        address_types = ['property', 'mailing']
        for address_type in address_types:
            address = {
                'street': '',
                'city': '',
                'state': '',
                'zip': '',
            }

            for field in address.keys():
                prefix = 'mailing_' if address_type == 'mailing' else ''
                upload_field = f'{field}code' if field == 'zip' else field
                column_name = f'{prefix}{upload_field}_column_number'
                data = self.__get_data_from_row(column_name, row)
                address[field] = data.title() if field in ['street', 'city'] else data

            addresses[address_type] = address

        property_address_obj = get_or_create_address(addresses['property'])
        mailing_address_obj = get_or_create_address(addresses['mailing'])

        # Now that we have the property and mailing address, we can create the property.
        if not property_address_obj:
            return None

        prop, new = Property.objects.get_or_create(
            company=self.upload.company,
            address=property_address_obj,
            defaults={
                'mailing_address': mailing_address_obj,
            },
        )

        # Count property.
        update_fields = ['properties_imported']
        self.upload.properties_imported = F('properties_imported') + 1
        if new:
            self.upload.new_properties = F('new_properties') + 1
            update_fields.append('new_properties')
            prop.upload_prospects = self.upload
            prop.save(update_fields=['upload_prospects'])
        else:
            self.upload.existing_properties = F('existing_properties') + 1
            update_fields.append('existing_properties')
        self.upload.save(update_fields=update_fields)

        return prop

    def __get_prospect_data_from_row(self, row):
        """
        Get data that applies to every `Prospect` created from row passed.
        """
        data = self.__get_name_and_email_from_row(row)
        data.update(self.__get_custom_fields_from_row(row))
        return data

    def __get_phone_list_from_row(self, row):
        """
        Return list of phones on row passed.
        """
        phone_list = []
        for phone_field_num in range(12):
            field_num = int(phone_field_num) + 1
            phone_raw = self.__get_data_from_row(f'phone_{field_num}_number', row)
            # Check if phone is mapped and not blank.
            if phone_raw:
                phone_clean = clean_phone(phone_raw)
                if phone_clean:
                    phone_list.append(phone_clean)

        return phone_list

    def __get_name_and_email_from_row(self, row):
        """
        Get name and email out of CSV row.
        """
        data = {}
        first_name = self.__get_data_from_row('first_name_column_number', row).title()
        last_name = self.__get_data_from_row('last_name_column_number', row).title()
        email = self.__get_data_from_row('email_column_number', row)
        if first_name or last_name or email:
            data = {'first_name': first_name, 'last_name': last_name, 'email': email}
        return data

    def __get_custom_fields_from_row(self, row):
        """
        Get custom fields out of CSV row.
        """
        custom = {}
        for i in range(1, 5):
            key = f'custom_{i}_column_number'
            new_key = f'custom{i}'
            custom[new_key] = self.__get_data_from_row(key, row)
        return custom

    def __get_data_from_row(self, column_name, row):
        """
        Given a column and a row, get the data out of the row in that column.
        """
        column_number = getattr(self.upload, column_name)
        # Verify the upload has this column (important for all uploads)
        # Also verify this column is in the row (Covers case in which .xls file is uploaded and
        # blank column is at the end of the row).
        if (column_number or column_number == 0) and len(row) > column_number:
            return row[int(column_number)].strip()
        return ''
