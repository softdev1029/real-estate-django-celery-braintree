import base64
from datetime import datetime, timedelta
import json

import pytz
import requests

from django.conf import settings
from django.db.models import F
from django.db.utils import DataError
from django.utils import timezone as django_tz

from core.utils import clean_phone
from prospects.utils import update_stacker_for_upload
from services.smarty import SmartyValidateAddresses
from sherpa.csv_uploader import ProcessUpload
from sherpa.models import Prospect
from sherpa.utils import get_data_from_column_mapping
from skiptrace.tasks import start_skip_trace_task
from .models import SkipTraceProperty
from .renderers import SkipTracePropertyRenderer
from .tasks import (
    send_skip_trace_confirmation_task,
    send_skip_trace_error_upload_email_task,
    validate_skip_trace_returned_address_task,
)


class ProcessSkipTraceUpload(ProcessUpload):
    """
    Save data from `UploadSkipTrace` whether from csv or single skip trace upload.
    """
    def __init__(self, upload):
        super().__init__(upload, upload_type='skip_trace', is_batch=True)

    def start(self):
        """
        Initialize upload, get data, and complete upload.
        """
        self.initialize_upload()

        if self.upload.is_single_upload:
            self.get_data_for_single_skip_trace()
        else:
            self.get_data_from_csv()

        self.complete_upload()

    def requeue_task(self):
        start_skip_trace_task.delay(self.upload.pk)

    def get_data_for_single_skip_trace(self):
        """
        Get data for a single skip trace.
        """
        error = None
        try:
            self.process_skip_trace_property(
                SkipTraceProperty.objects.get(upload_skip_trace=self.upload))
        except Exception as e:
            error = e
        error = error if error else self.upload.upload_single()

        if not error:
            self.increment_last_row_processed()
        else:
            self.set_error(error)

        self.success = self.upload.single_upload_authorized

    def complete_upload(self):
        """
        If upload was successful, set status as complete, charge, and send confirmation email.
        """
        if self.success:
            super().complete_upload()

            # Charge for skip trace here if not Cedar Crest (id=1)
            if not self.upload.company.is_billing_exempt and not \
                    self.upload.is_single_upload:
                self.upload.charge()

            send_skip_trace_confirmation_task(self.upload.id)
        elif self.cancelled:
            if not self.upload.company.is_billing_exempt and not \
                    self.upload.is_single_upload:
                self.upload.charge()

            send_skip_trace_confirmation_task(self.upload.id)

        update_stacker_for_upload(self.upload)

    def process_skip_trace_property(self, skip_trace_property, is_duplicate=False):
        """
        Process a single `SkipTraceProperty` to update it with address and phone data.
        """
        process_record = ProcessSkipTraceRecord(skip_trace_property, self.upload, is_duplicate)
        process_record.start()
        if skip_trace_property.has_litigator and not is_duplicate:
            self.upload.total_litigators = F('total_litigators') + 1
            self.upload.save(update_fields=['total_litigators'])

    def set_error(self, error_message):
        """
        Set error message and send error email.
        :param error_message: Error message to save (string).
        """
        super().set_error(error_message)
        send_skip_trace_error_upload_email_task.delay(self.upload.id)

    def process_record_from_csv_row(self, row, is_callback=False):
        """
        Create `SkipTraceProperty` from data in csv and process new `SkipTraceProperty`.
        """
        column_fields = [
            'fullname',
            'first_name',
            'last_name',
            'property_street',
            'property_city',
            'property_state',
            'property_zipcode',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zipcode',
            'custom_1',
            'custom_2',
            'custom_3',
            'custom_4',
            'custom_5',
            'custom_6',
        ]

        data = get_data_from_column_mapping(column_fields, row, self.upload)
        if data:
            params = {
                'upload_skip_trace': self.upload,
                'submitted_owner_fullname': data['fullname'],
                'submitted_owner_first_name': data['first_name'],
                'submitted_owner_last_name': data['last_name'],
                'submitted_property_address': data['property_street'],
                'submitted_property_city': data['property_city'],
                'submitted_property_state': data['property_state'],
                'submitted_property_zip': data['property_zipcode'],
                'submitted_mailing_address': data['mailing_street'],
                'submitted_mailing_city': data['mailing_city'],
                'submitted_mailing_state': data['mailing_state'],
                'submitted_mailing_zip': data['mailing_zipcode'],
                'submitted_custom_1': data['custom_1'],
                'submitted_custom_2': data['custom_2'],
                'submitted_custom_3': data['custom_3'],
                'submitted_custom_4': data['custom_4'],
                'submitted_custom_5': data['custom_5'],
                'submitted_custom_6': data['custom_6'],
            }
            # Using 'filter().first()' instead of 'get_or_create()' to handle the rare case of
            # more than one matching record.
            skip_trace_property = SkipTraceProperty.objects.filter(**params).first()
            is_duplicate = True
            if not skip_trace_property:
                skip_trace_property = SkipTraceProperty.objects.create(**params)
                is_duplicate = False

            if not is_callback:
                self.process_skip_trace_property(skip_trace_property, is_duplicate=is_duplicate)
            else:
                data = {
                    'duplicate': is_duplicate,
                    'skip_trace_id': skip_trace_property,
                }
                return data

    def process_records_from_csv_batch(self, batch):
        """
        Create `SkipTraceProperty` from data in csv and process new `SkipTraceProperty` for batch.
        """
        skip_trace_property_recs = []
        for an_row in batch:
            resp = self.process_record_from_csv_row(an_row, is_callback=True)
            # If there's bad data, we just need to skip it.
            if not resp:
                self.increment_last_row_processed()
                continue

            skip_trace_property_recs.append(resp)
        self.process_skip_trace_property_by_batch(skip_trace_property_recs)

    def process_skip_trace_property_by_batch(self, skip_trace_property_recs):
        """
        Process as batch of `SkipTraceProperty` records to update it with address and phone data.
        """
        process_record = ProcessSkipTraceRecord(skip_trace_property=skip_trace_property_recs,
                                                upload_skip_trace=self.upload)
        process_record.start_batch()
        for an_obj in skip_trace_property_recs:
            if an_obj['skip_trace_id'].has_litigator and not an_obj['duplicate']:
                self.upload.total_litigators = F('total_litigators') + 1
                self.upload.save(update_fields=['total_litigators'])


class ProcessSkipTraceRecord:
    """
    Validate addresses and get info from IDI (or copy from existing) for a `SkipTraceProperty`.
    """
    def __init__(self, skip_trace_property, upload_skip_trace, is_duplicate=False):
        self.skip_trace_property = skip_trace_property
        self.upload_skip_trace = upload_skip_trace
        self.is_duplicate = is_duplicate
        self.internal_hit = False
        self.match_expiration_days = 150

    def start(self):
        """
        Validate addresses then copy from existing records or get new data from IDI.
        """
        # If this is a duplicate within the upload file, update hit stats and stop processing.
        if self.is_duplicate:
            self.update_hit_stats()
            return

        self.validate_skip_trace_addresses()

        # Get data from IDI if no match found or 'Suppress Against Database' turned off.
        if not self.upload_skip_trace.suppress_against_database or not self.copy_from_match():
            self.update_from_idi()

        # Skip Trace Property is created. Now, create `Prospects`.
        Prospect.objects.create_from_skip_trace_property(self.skip_trace_property)

    def increment_last_row_processed(self):
        """
        Increment last row processed.
        """
        self.upload_skip_trace.last_row_processed = F('last_row_processed') + 1
        self.upload_skip_trace.save(update_fields=['last_row_processed'])

    def set_error(self, address_validation_err, skip_trace_property_obj):
        """
        Set error for batch `SkipTraceProperty` records.
        """
        for an_rec in skip_trace_property_obj:
            an_rec['skip_trace_id'].upload_error = address_validation_err
            an_rec['skip_trace_id'].save(update_fields=['upload_error'])

    def __get_or_update_duplicated_skip_trace_rec(self):
        """
        Update duplicate within the processed file and update hit stats.
        """
        req_list = []
        for an_obj in self.skip_trace_property:
            if not an_obj:
                self.increment_last_row_processed()
                continue

            if an_obj['duplicate']:
                self.duplicate = True
                self.internal_hit = False
                self.skip_trace_property = an_obj['skip_trace_id']
                self.update_hit_stats()
                self.increment_last_row_processed()
            else:
                req_list.append(an_obj)
        return req_list

    def __format_and_save_skip_trace_address_in_batch(self, skip_trace_property_obj):
        """
        Invock and save smarty street api in batch.
        """
        address_validator = SmartyValidateAddresses(
            [x['skip_trace_id'] for x in skip_trace_property_obj],
            self.upload_skip_trace.company,
        )
        address_validator.validate_addresses()

        if address_validator.error:
            self.set_error(address_validator.error, skip_trace_property_obj)

        for pk in address_validator.results:
            SkipTraceProperty.objects.filter(pk=pk).update(**address_validator.results[pk])

    def __update_skip_trace_rec_from_idi_data(self, skip_trace_property_obj):
        """
        Invock or save `SkipTraceProperty` record based on IDI data.
        """
        for an_rec in skip_trace_property_obj:
            self.duplicate = False
            self.skip_trace_property = an_rec['skip_trace_id']
            self.skip_trace_property.refresh_from_db()
            self.internal_hit = False

            # Get data from IDI if no match found or 'Suppress Against Database' turned off.
            if not self.upload_skip_trace.suppress_against_database or not self.copy_from_match():
                self.update_from_idi()

            # Skip Trace Property is created. Now, create `Prospects`.
            Prospect.objects.create_from_skip_trace_property(self.skip_trace_property)
            self.increment_last_row_processed()

    def start_batch(self):
        """
        Replication of self.start method based on batch processing.
        """
        deduplicated_recs = self.__get_or_update_duplicated_skip_trace_rec()
        self.__format_and_save_skip_trace_address_in_batch(deduplicated_recs)
        self.__update_skip_trace_rec_from_idi_data(deduplicated_recs)

    def validate_skip_trace_addresses(self):
        """
        Validate mailing and property addresses for a `SkipTraceProperty`.
        """
        if settings.TEST_MODE:
            return

        address_validator = SmartyValidateAddresses(
            self.skip_trace_property,
            self.upload_skip_trace.company,
        )
        address_validator.validate_addresses()

        if address_validator.error:
            self.skip_trace_property.upload_error = address_validator.error
            self.skip_trace_property.save(update_fields=['upload_error'])

    def copy_from_match(self):
        """
        Copy data into `SkipTraceProperty` if match is found.
        """
        copied_from_match = self.copy_from_matching_skip_trace_properties()
        if not copied_from_match:
            copied_from_match = self.copy_from_matching_prospects()

        if copied_from_match:
            self.update_hit_stats(copy_from_existing=True)

        return copied_from_match

    def update_from_idi(self, force_property_search=False, force_mailing_search=False):
        """
        Update data from IDI. If full search returns no hits, try again with property search.
        """
        if settings.TEST_MODE:
            self.idi_test_mode()
            return

        get_from_idi = UpdateFromIDI(
            self.upload_skip_trace,
            self.skip_trace_property,
            force_property_search,
            force_mailing_search,
        )
        get_from_idi.get()

        self.update_hit_stats()
        if self.skip_trace_property.has_hit:
            validate_skip_trace_returned_address_task.delay(self.skip_trace_property.id)
        elif not get_from_idi.mailing_only_search and not get_from_idi.property_only_search:
            self.update_from_idi(force_mailing_search=True)
        elif get_from_idi.mailing_only_search:
            # Re-run as property only search if there's no hits on full search.
            self.update_from_idi(force_property_search=True)

    def copy_from_matching_skip_trace_properties(self):
        """
        Copy data to `SkipTraceProperty` from matching `SkipTraceProperty` objects.
        """
        matching_skip_trace_properties = self.get_matching_skip_trace_properties()
        # There's no matches, so copy failed.
        if not matching_skip_trace_properties:
            return False

        # Copy name, if it's still blank then copy failed (need to get it from IDI).
        if not self.copy_missing_name(matching_skip_trace_properties, match_is_skip_trace=True):
            return False

        self.copy_missing_mailing_address(matching_skip_trace_properties, match_is_skip_trace=True)
        self.copy_relative_data(matching_skip_trace_properties)

        update_fields = [
            'has_hit',
            'returned_fullname',
            'returned_first_name',
            'returned_last_name',
            'returned_phone_1',
            'returned_phone_2',
            'returned_phone_3',
            'returned_phone_4',
            'returned_phone_5',
            'returned_phone_type_1',
            'returned_phone_type_2',
            'returned_phone_type_3',
            'returned_phone_type_4',
            'returned_phone_type_5',
            'returned_phone_is_disconnected_1',
            'returned_phone_is_disconnected_2',
            'returned_phone_is_disconnected_3',
            'returned_phone_is_disconnected_4',
            'returned_phone_is_disconnected_5',
            'returned_phone_carrier_1',
            'returned_phone_carrier_2',
            'returned_phone_carrier_3',
            'returned_phone_carrier_4',
            'returned_phone_carrier_5',
            'returned_phone_last_seen_1',
            'returned_phone_last_seen_2',
            'returned_phone_last_seen_3',
            'returned_phone_last_seen_4',
            'returned_phone_last_seen_5',
            'returned_email_1',
            'returned_email_2',
            'returned_email_3',
            'returned_email_last_seen_1',
            'returned_email_last_seen_2',
            'returned_email_last_seen_3',
            'returned_address_1',
            'returned_city_1',
            'returned_state_1',
            'returned_zip_1',
            'returned_address_last_seen_1',
            'returned_address_2',
            'returned_city_2',
            'returned_state_2',
            'returned_zip_2',
            'returned_address_last_seen_2',
            'returned_ip_address',
            'returned_ip_last_seen',
            'age',
            'deceased',
            'bankruptcy',
            'returned_foreclosure_date',
            'returned_lien_date',
            'returned_judgment_date',
            'validated_returned_address_1',
            'validated_returned_address_2',
            'validated_returned_city_1',
            'validated_returned_state_1',
            'validated_returned_zip_1',
            'validated_returned_property_status',
            'is_existing_match',
            'existing_match_prospect_id',
        ]
        for field in update_fields:
            setattr(
                self.skip_trace_property,
                field,
                getattr(matching_skip_trace_properties[0], field),
            )
        self.skip_trace_property.is_existing_match = not self.internal_hit
        self.skip_trace_property.save(update_fields=update_fields)
        return True

    def copy_from_matching_prospects(self):
        """
        Copy data to `SkipTraceProperty` from matching `Prospect` objects.
        """
        matching_prospects = self.get_matching_prospects()
        # If there's no matches, copy failed.
        if not matching_prospects:
            return False

        # Copy name, if it's still blank then copy failed (need to get it from IDI).
        if not self.copy_missing_name(matching_prospects):
            return False

        self.copy_missing_mailing_address(matching_prospects)

        # Get up to 3 matching phone numbers
        for i, matching_prospect in enumerate(matching_prospects):
            if i > 2:
                break
            phone_count = str(i + 1)
            setattr(self.skip_trace_property, f'returned_phone_{phone_count}',
                    matching_prospect.phone_raw)
            setattr(self.skip_trace_property, f'returned_phone_type_{phone_count}',
                    matching_prospect.phone_type)
            setattr(self.skip_trace_property, f'returned_phone_carrier_{phone_count}',
                    matching_prospect.phone_carrier)
            setattr(self.skip_trace_property, f'matching_prospect_id_{phone_count}',
                    matching_prospect.id)

        self.skip_trace_property.is_existing_match = not self.internal_hit
        self.skip_trace_property.has_hit = True
        self.skip_trace_property.existing_match_prospect_id = matching_prospects[0].id

        update_fields = [
            'has_hit',
            'returned_phone_1',
            'returned_phone_2',
            'returned_phone_3',
            'returned_phone_type_1',
            'returned_phone_type_2',
            'returned_phone_type_3',
            'returned_phone_carrier_1',
            'returned_phone_carrier_2',
            'returned_phone_carrier_3',
            'matching_prospect_id_1',
            'matching_prospect_id_2',
            'matching_prospect_id_3',
            'is_existing_match',
            'existing_match_prospect_id',
        ]
        self.skip_trace_property.save(update_fields=update_fields)

        return True

    def idi_test_mode(self):
        """
        Fake getting a phone number from IDI in order to test.
        """
        self.skip_trace_property.returned_phone_1 = 5555555555
        self.skip_trace_property.save(update_fields=['returned_phone_1'])
        self.update_hit_stats()

    def update_hit_stats(self, copy_from_existing=False):
        """
        Update hit stats when getting data
        """
        update_fields = []
        if copy_from_existing and not self.internal_hit:
            self.upload_skip_trace.total_existing_matches = F('total_existing_matches') + 1
            update_fields.append('total_existing_matches')

        # If there was a phone, email or address returned, this was a hit.
        if self.skip_trace_property.returned_phone_1 or \
                self.skip_trace_property.returned_email_1 or \
                self.skip_trace_property.returned_address_1:
            self.skip_trace_property.has_hit = True
            self.skip_trace_property.save(update_fields=['has_hit'])
            self.upload_skip_trace.total_hits = F('total_hits') + 1
            update_fields.append('total_hits')

            # If this is a duplicate within the file, update stats and stop here.
            if self.is_duplicate:
                self.upload_skip_trace.save(update_fields=update_fields)
                return

            # Only bill new hits.
            if not copy_from_existing or self.internal_hit:
                self.upload_skip_trace.total_billable_hits = F('total_billable_hits') + 1
                update_fields.append('total_billable_hits')
            if self.internal_hit:
                self.upload_skip_trace.total_internal_hits = F('total_internal_hits') + 1
                update_fields.append('total_internal_hits')

        # Count up to 3 phone numbers, 2 emails and 2 addresses
        fields = ['phone', 'email', 'address']
        for field in fields:
            for i in range(3):
                if i < 2 or field == 'phone':
                    val = getattr(self.skip_trace_property, f'returned_{field}_{i + 1}')
                    if val:
                        total_field = f'total_{field}' if field != 'address' else f'total_{field}es'
                        setattr(
                            self.upload_skip_trace,
                            total_field,
                            getattr(self.upload_skip_trace, total_field, 0) + 1,
                        )
                        update_fields.append(total_field)
        self.upload_skip_trace.save(update_fields=update_fields)

    def get_matching_skip_trace_properties(self, property_only=False, all_companies=False):
        """
        Get `SkipTraceProperty` objects that match on validated mailing address or property address.

        By default this searches the `Company` tied to the `SkipTraceProperty` and checks for
        matching mailing address, then for matching property address.
        'property_only' set to True will search property address only. 'all_companies' set to True
        will search for matches in any `Company`.
        """
        field_prefix = None
        if self.skip_trace_property.validated_mailing_status == 'validated' and not property_only:
            field_prefix = 'validated_mailing_'
        elif self.skip_trace_property.validated_property_status == 'validated':
            field_prefix = 'validated_property_'
        if field_prefix:
            delivery_line_1 = getattr(self.skip_trace_property, f'{field_prefix}delivery_line_1')
            delivery_line_2 = getattr(self.skip_trace_property, f'{field_prefix}delivery_line_2')
            zip_code = getattr(self.skip_trace_property, f'{field_prefix}zipcode')
            filters = {
                'has_hit': True,
                f'{field_prefix}status': 'validated',
                f'{field_prefix}delivery_line_1': delivery_line_1,
                f'{field_prefix}delivery_line_2': delivery_line_2,
                f'{field_prefix}zipcode': zip_code,
            }
            if not all_companies:
                filters['upload_skip_trace__company'] = \
                    self.skip_trace_property.upload_skip_trace.company
            else:
                filters['created__gt'] = django_tz.now() - timedelta(
                    days=self.match_expiration_days)

            matches = SkipTraceProperty.objects.filter(**filters).exclude(
                id=self.skip_trace_property.id)
            if not matches and field_prefix == 'validated_mailing_':
                return self.get_matching_skip_trace_properties(
                    property_only=True,
                    all_companies=all_companies,
                )
            if not matches and not all_companies:
                return self.get_matching_skip_trace_properties(all_companies=True)
            self.internal_hit = matches and all_companies
            return matches
        return []

    def get_matching_prospects(self):
        """
        Get matching `Prospect` objects that match on validated property address.

        Only check for user's company (no charge) because there's no relative info to return.
.       """
        matches = []
        if self.skip_trace_property.validated_property_status == 'validated':
            delivery_line_1 = self.skip_trace_property.validated_property_delivery_line_1
            delivery_line_2 = self.skip_trace_property.validated_property_delivery_line_2
            address = f"{delivery_line_1} {delivery_line_2}" if delivery_line_2 else delivery_line_1
            filters = {
                'property_address': address,
                'property_zip': self.skip_trace_property.validated_property_zipcode,
                'company': self.skip_trace_property.upload_skip_trace.company,
            }
            matches = Prospect.objects.filter(**filters).order_by('-id')

        return matches

    def copy_missing_name(self, prospects, match_is_skip_trace=False):
        """
        If there's no name, copy name and return whether or not copy was successful.
        """
        if not self.skip_trace_property.blank_name:
            return True

        get_name_from = prospects[0]
        if get_name_from.blank_name:
            for match in prospects:
                if not match.blank_name:
                    get_name_from = match
                    break

        self.skip_trace_property.copy_name_from_prospect(
            get_name_from, is_skip_trace=match_is_skip_trace)

        return not self.skip_trace_property.blank_name

    def copy_missing_mailing_address(self, prospects, match_is_skip_trace=False):
        """
        If there's no mailing address, copy from prospect or from property address.
        """
        # We have an address, no need to copy.
        if self.skip_trace_property.submitted_mailing_address:
            return

        # Get a prospect that has a mailing address if one exists.
        prospect = prospects[0]
        mailing_field = 'mailing_address'
        if match_is_skip_trace:
            mailing_field = 'submitted_mailing_address'
        if not getattr(prospect, mailing_field):
            for current_prospect in prospects:
                if getattr(prospect, mailing_field):
                    prospect = current_prospect
                    break

        self.skip_trace_property.copy_address_from_prospect(prospect, match_is_skip_trace)
        if self.skip_trace_property.submitted_mailing_address:
            self.validate_skip_trace_addresses()
        else:
            self.skip_trace_property.copy_mailing_address()

    def copy_relative_data(self, matches):
        """
        Copy relative's information from matching `SkipTraceProperty` objects.
        """
        # Get a match that has a relative phone if one exists.
        match = matches[0]
        relative_phone_field = 'relative_1_phone1'

        if not getattr(match, relative_phone_field):
            for current_match in matches:
                if getattr(current_match, relative_phone_field):
                    match = current_match
                    break
        self.skip_trace_property.copy_relative_data(match)


class UpdateFromIDI:
    """
    Call IDI and save data to `SkipTraceProperty`.
    """
    def __init__(
            self,
            upload_skip_trace,
            skip_trace_property,
            force_property_only_search=False,
            force_mailing_search=False,
    ):
        self.upload_skip_trace = upload_skip_trace
        self.skip_trace_property = skip_trace_property
        self.property_only_search = force_property_only_search
        self.mailing_only_search = force_mailing_search

    def get(self):
        """
        Get phone numbers, emails, and other additional data from IDI.
        """
        missing_mailing_address = not self.skip_trace_property.\
            submitted_mailing_address or self.skip_trace_property.blank_name
        if missing_mailing_address or self.property_only_search:
            self.property_only_search = True
            search_criteria = self.get_property_only_search_criteria()
            if not self.skip_trace_property.submitted_mailing_address:
                self.skip_trace_property.copy_mailing_address()
        else:
            search_criteria = self.get_full_search_criteria()

        if search_criteria:
            response = self.idi_run_search(search_criteria)
            self.save_data_from_idi_response(response)

    def get_property_only_search_criteria(self):
        """
        Format data in `SkipTraceProperty` to search IDI by property address fields only.
        """
        search_criteria = self.format_search_criteria()

        # We have to search by property address to get pid list first.
        search_criteria.update({"fields": ["property"]})
        response = self.idi_run_search(search_criteria)

        try:
            response_json = response.json()
            result = response_json['result'][0]
            pid_list = result['property'][0]['owner'][0]['personName'][0]['pidlist']
        except (KeyError, IndexError):
            return None

        # We are using pid list to search instead of name and address fields.
        return {"pidlist": pid_list,
                "fields": ["name", "address", "phone", "email", "bankruptcy", "dob", "relationship",
                           "isDead", "ip", "lien", "judgment", "foreclosure"],
                }

    def get_full_search_criteria(self):
        """
        Format data in `SkipTraceProperty` to search IDI by name and address, prioritizing
        validated mailing address.
        """
        search_criteria = self.format_search_criteria()
        search_criteria.update({
            "fields": ["name", "address", "phone", "email", "bankruptcy", "dob", "relationship",
                       "isDead", "ip", "lien", "judgment", "foreclosure"],
        })
        return search_criteria

    def idi_run_search(self, search_criteria):
        """
        Run IDI search and return results for given data.
        """
        if not self.upload_skip_trace.has_valid_idi_token:
            self.set_idi_token()

        url = settings.IDI_API_BASE_URL + 'search/'

        headers = {
            'authorization': self.upload_skip_trace.idi_token,
            'content-type': "application/json",
            'accept': "application/json",
        }

        json_body = json.dumps(search_criteria)
        return requests.request("POST", url, data=json_body, headers=headers)

    def save_data_from_idi_response(self, response):
        """
        Save data returned in IDI response.
        """
        result = self.decode_idi_result(response)

        if not result:
            return

        self.get_name_from_idi(result)
        self.get_phone_numbers_from_idi(result.get('phone', []))
        self.get_emails_from_idi(result.get('email', []))
        self.get_addresses_from_idi(result.get('address', []))
        self.get_relationship_data_from_idi(result.get('relationship', []))
        self.get_ip_from_idi(result.get('ip', []))
        self.get_date_fields_from_idi(result)
        self.skip_trace_property.deceased = result.get('isDead', False)
        age = ''
        try:
            age = result['dob'][0]['age']
            self.skip_trace_property.bankruptcy = result['bankruptcy'][0]['filingDate']['data']
        except (KeyError, IndexError):
            pass

        try:
            self.skip_trace_property.age = int(age)
        except (ValueError, TypeError):
            pass

        try:
            self.skip_trace_property.save()
        except DataError:
            # The IP address received from idi can sometimes be invalid and should be cleared.
            self.get_ip_from_idi([])
            self.skip_trace_property.returned_ip_address = None
            self.skip_trace_property.returned_ip_last_seen = None
            self.skip_trace_property.save()

    def format_search_criteria(self):
        """
        Format search criteria to prepare to call IDI
        """
        data = {}
        if self.property_only_search:
            address_types = ['property']
        elif self.mailing_only_search:
            address_types = ['mailing']
        else:
            address_types = ['mailing', 'property']
            data = self.format_name_for_search()

        validated_type = None
        submitted_type = 'property'
        for address_type in address_types:
            validated = self.skip_trace_property.address_validated(
                is_property_address=address_type == 'property')
            if validated:
                validated_type = address_type
                break
            elif submitted_type == 'property':
                submitted_address = \
                    getattr(self.skip_trace_property, f'submitted_{address_type}_address')
                submitted_zip = getattr(self.skip_trace_property, f'submitted_{address_type}_zip')
                if submitted_address and submitted_zip:
                    submitted_type = address_type

        address_type = validated_type if validated_type else submitted_type
        address_line = self.format_address_line_for_search(
            validated_type is not None, address_type)
        field_names = self.get_fields_for_search(validated_type is not None, address_type)

        data.update({
            "address": address_line,
            "city": getattr(self.skip_trace_property, field_names['city_field'], ''),
            "state": getattr(self.skip_trace_property, field_names['state_field'], ''),
            "zip": getattr(self.skip_trace_property, field_names['zip_field'], ''),
        })
        return data

    def set_idi_token(self):
        """
        Authenticate with IDI and set token.
        """
        url = settings.IDI_LOGIN_BASE_URL + "apiclient"
        client_id = settings.IDI_CLIENT_ID
        client_secret = settings.IDI_CLIENT_SECRET

        payload = "{\"glba\":\"liability\",\"dppa\":\"verification\"}"
        headers = {
            'authorization': "Basic " + base64.encodebytes(
                (client_id + ":" + client_secret).encode()).decode().replace("\n", ""),
            'content-type': "application/json",
        }

        response = requests.request("POST", url, data=payload, headers=headers)

        if response.status_code != 200:
            raise ConnectionRefusedError("Could not authenticate with IDI.")

        self.upload_skip_trace.last_idi_token_reset = django_tz.now()
        self.upload_skip_trace.idi_token = response.text
        self.upload_skip_trace.save(update_fields=['last_idi_token_reset', 'idi_token'])

    def decode_idi_result(self, response):
        """
        Decode IDI result into JSON. If there's no result, re-run with property only search.
        """
        try:
            response_json = response.json()
        except ValueError:
            self.set_skip_trace_status('Error: No JSON object could be decoded', reset_token=True)
            return dict()

        if not response_json['result']:
            self.set_skip_trace_status('Error: No Result found', reset_token=True)
            return dict()

        self.set_skip_trace_status(response.status_code)
        return response_json['result'][0]

    def get_name_from_idi(self, result):
        """
        Get name returned from IDI. If there's no submitted name, copy name to submitted name.
        """
        first_name = ''
        last_name = ''
        fullname = ''
        if 'name' in result:
            name = result['name'][0]
            first_name = name['first'].title()
            last_name = name['last'].title()
            fullname = name['data'].title()

        self.skip_trace_property.returned_first_name = first_name
        self.skip_trace_property.returned_last_name = last_name
        self.skip_trace_property.returned_fullname = fullname

        if self.skip_trace_property.blank_name:
            self.skip_trace_property.submitted_owner_first_name = first_name.title()
            self.skip_trace_property.submitted_owner_last_name = last_name.title()
            self.skip_trace_property.submitted_owner_fullname = fullname.title()

    def get_phone_numbers_from_idi(self, phone_list):
        """
        Get up to 5 phone numbers out of phone_list returned from IDI.
        """
        phone_schema = {
            'number': 'phone',
            'type': 'phone_type',
            'disconnected': 'phone_is_disconnected',
            'providerName': 'phone_carrier',
            'meta': 'phone_last_seen',
        }
        self.get_data_from_idi_list(phone_list, phone_schema, cap=5)

    def get_emails_from_idi(self, email_list):
        """
        Get up to 3 emails out of email_list returned from IDI
        """
        email_schema = {
            'data': 'email',
            'meta': 'email_last_seen',
        }
        self.get_data_from_idi_list(email_list, email_schema, cap=3)

    def get_addresses_from_idi(self, address_list):
        """
        Get up to 2 addresses out of address_list from IDI.
        """
        address_schema = {
            'complete': 'address',
            'city': 'city',
            'state': 'state',
            'zip': 'zip',
            'meta': 'address_last_seen',
        }
        self.get_data_from_idi_list(address_list, address_schema, cap=2)

    def get_relationship_data_from_idi(self, relationship_list):
        """
        Get data from up to 2 relationships out of relationship_list from IDI.
        """
        relationship_schema = {
            'name': 'relative',
            'phone': 'relative',
        }
        self.get_data_from_idi_list(relationship_list, relationship_schema, cap=2)

    def get_ip_from_idi(self, ip_list):
        """
        Get first IP out of ip_list returned from IDI
        """
        ip_schema = {
            'data': 'ip_address',
            'meta': 'ip_last_seen',
        }
        self.get_data_from_idi_list(ip_list, ip_schema, cap=1, count_suffix=False)

    def get_date_fields_from_idi(self, result):
        """
        Get sortable date from idi result for date fields and save to `SkipTraceProperty`
        """
        date_fields = ['lien', 'judgment', 'foreclosure']

        for field in date_fields:
            data = result.get(field, [])
            if data:
                if field == 'foreclosure':
                    detail = data[0].get('detail')
                    date_data = detail[0].get('documentDate') if detail else None
                else:
                    record = data[0].get('record')
                    date_data = record[0].get('date') if record else None

                if not date_data:
                    # The date data is sometimes not available from idi.
                    return

                sortable_date = date_data.get('sortable')
                if sortable_date:
                    setattr(
                        self.skip_trace_property,
                        f'returned_{field}_date',
                        datetime.strptime(str(sortable_date), '%Y%m%d').date(),
                    )

    def format_name_for_search(self):
        """
        Get first and last name and parse our middle name for IDI search.
        """
        last_name = self.skip_trace_property.submitted_owner_last_name or ''
        first_name = self.skip_trace_property.submitted_owner_first_name or ''

        # Parse out middle initial if there is one.
        first_name_list = first_name.split()
        if len(first_name_list) > 1:
            second_word = first_name_list[1]
            if len(second_word) == 1:
                first_name = first_name_list[0]

        return {"lastName": last_name, "firstName": first_name}

    def format_address_line_for_search(self, address_validated, address_type):
        """
        Format address line for IDI search based on address type in field
        """
        delivery_line_2 = ''
        if address_validated:
            field_prefix = f'validated_{address_type}_'
            delivery_line_1 = getattr(self.skip_trace_property, f'{field_prefix}delivery_line_1')
            delivery_line_2 = getattr(self.skip_trace_property, f'{field_prefix}delivery_line_2')
        else:
            delivery_line_1 = \
                getattr(self.skip_trace_property, f'submitted_{address_type}_address')
        address_line = delivery_line_1
        if delivery_line_2:
            address_line += f' {delivery_line_2}'

        return address_line

    @staticmethod
    def get_fields_for_search(address_validated, address_type):
        """
        Get field names for search based on validated address type.
        """
        city_suffix = 'city'
        state_suffix = 'state'
        zip_suffix = 'zip'
        field_prefix = f'submitted_{address_type}_'
        if address_validated:
            field_prefix = f'validated_{address_type}_'
            city_suffix += '_name'
            state_suffix += '_abbreviation'
            zip_suffix += 'code'

        return {
            'city_field': f'{field_prefix}{city_suffix}',
            'state_field': f'{field_prefix}{state_suffix}',
            'zip_field': f'{field_prefix}{zip_suffix}',
        }

    def set_skip_trace_status(self, status, reset_token=False):
        """
        Set status of `SkipTraceProperty` (indicates status of IDI call).
        """
        self.skip_trace_property.skip_trace_status = status
        self.skip_trace_property.save(update_fields=['skip_trace_status'])
        if reset_token and not self.upload_skip_trace.has_valid_idi_token:
            self.upload_skip_trace.last_idi_token_reset = None
            self.upload_skip_trace.idi_token = ''
            self.upload_skip_trace.save(update_fields=['last_idi_token_reset', 'idi_token'])

    def get_data_from_idi_list(self, data_list, schema, cap, count_suffix=True):
        """
        Get data out of list returned from IDI ad save to `SkipTraceProperty`.
        """
        for index, data in enumerate(data_list):
            if index == cap:
                break
            for key in schema:
                try:
                    update_data = self.format_idi_data_to_update(
                        data,
                        key,
                        schema,
                        index,
                        count_suffix,
                    )

                    for field_name in update_data:
                        setattr(self.skip_trace_property, field_name, update_data[field_name])
                except (ValueError, KeyError):
                    pass

    @staticmethod
    def format_idi_data_to_update(data, key, schema, index, count_suffix=True):
        """
        Format data from IDI to be saved.
        """
        update_data = dict()
        # Default value. If this is a phone list, name or meta data, value will change.
        val = data[key]

        i = index + 1
        if key == 'number':
            val = clean_phone(val)
        if key == 'meta':
            last_seen = data[key]['lastSeen']
            val = datetime.strptime(str(last_seen), '%Y%m%d').date()
        if key == 'name':
            update_data = {
                f'{schema[key]}_{i}_first_name': val['first'].title(),
                f'{schema[key]}_{i}_last_name': val['last'].title(),
            }
        elif key == 'phone':
            for j, phone in enumerate(val):
                phone_key = f'{schema[key]}_{i}_phone{j + 1}'
                update_data[phone_key] = clean_phone(val[j]['number'])
                if j == 2:
                    break
        else:
            if schema[key] == 'phone_type' and val == 'Residential':
                val = 'Landline'

            key_name = f'returned_{schema[key]}'
            if count_suffix:
                key_name += f'_{i}'
            update_data = {key_name: val}

        return update_data


class SkipTraceCSVData:
    """
    Format data in uploaded Skip Trace so it can be exported to csv.
    """
    def __init__(self, upload_skip_trace):
        """
        :param upload_skip_trace: `UploadSkipTrace` object we want to get data from
        """
        self.upload_skip_trace = upload_skip_trace
        # All `SkipTraceProperty` objects tied to ths `UploadSkipTrace`.
        self.skip_trace_properties = SkipTraceProperty.objects.filter(
            upload_skip_trace=self.upload_skip_trace)
        self.filename = self.__get_filename()
        # We need data in a list format for the legacy view. Will be deprecated in the future.
        self.data_list = list()
        self.data_dict = list()

    def __get_filename(self):
        """
        Create file name as a .csv based on current date/time and company name.
        """
        datetime_now_local = datetime.now(pytz.timezone(self.upload_skip_trace.company.timezone))
        company_name_raw = self.upload_skip_trace.company.name
        company_name = company_name_raw.replace(",", "")
        return "SKIP-TRACE-%s-%s.csv" % (company_name, datetime_now_local)

    def format_data(self):
        """
        Loop thorough all `SkipTraceProperty` objects for the Skip Trace we're going to export,
        and format data so we can write it to a csv.

        We need this data in a list format for the legacy export view (to be deprecated) and a
        list of dict() with headers in `SkipTracePropertyRenderer` as the keys for the viewset.
        """
        for skip_trace_property in self.skip_trace_properties:
            # Get validated returned address and validated mailing address.
            validated_returned_address, validated_mailing_address = \
                self.__get_validated_addresses(skip_trace_property)

            # Get golden address
            golden_address, golden_city, golden_state, golden_zip, golden_address_last_seen = \
                self.__get_golden_address(skip_trace_property, validated_returned_address)

            # Save values to list (to be used for legacy view) and to be used for the values in
            # the dict() used by the new viewset.
            current_record_values = [
                skip_trace_property.submitted_owner_fullname,
                skip_trace_property.submitted_owner_first_name,
                skip_trace_property.submitted_owner_last_name,
                skip_trace_property.submitted_mailing_address,
                skip_trace_property.submitted_mailing_city,
                skip_trace_property.submitted_mailing_state,
                skip_trace_property.submitted_mailing_zip,
                skip_trace_property.submitted_property_address,
                skip_trace_property.submitted_property_city,
                skip_trace_property.submitted_property_state,
                skip_trace_property.submitted_property_zip,
                skip_trace_property.submitted_custom_1,
                skip_trace_property.submitted_custom_2,
                skip_trace_property.submitted_custom_3,
                skip_trace_property.submitted_custom_4,
                skip_trace_property.submitted_custom_5,
                skip_trace_property.submitted_custom_6,
                validated_mailing_address,
                skip_trace_property.validated_mailing_city_name,
                skip_trace_property.validated_mailing_state_abbreviation,
                skip_trace_property.validated_mailing_zipcode,
                skip_trace_property.validated_mailing_vacant,
                self.__proper_case(skip_trace_property.returned_fullname),
                self.__proper_case(skip_trace_property.returned_first_name),
                self.__proper_case(skip_trace_property.returned_last_name),
                skip_trace_property.returned_phone_1,
                skip_trace_property.returned_phone_type_1,
                skip_trace_property.returned_phone_last_seen_1,
                skip_trace_property.returned_phone_2,
                skip_trace_property.returned_phone_type_2,
                skip_trace_property.returned_phone_last_seen_2,
                skip_trace_property.returned_phone_3,
                skip_trace_property.returned_phone_type_3,
                skip_trace_property.returned_phone_last_seen_3,
                self.__proper_case(skip_trace_property.returned_email_1, title=False),
                skip_trace_property.returned_email_last_seen_1,
                self.__proper_case(skip_trace_property.returned_email_2, title=False),
                skip_trace_property.returned_email_last_seen_2,
                skip_trace_property.returned_ip_address,
                skip_trace_property.returned_ip_last_seen,
                self.__proper_case(golden_address),
                self.__proper_case(golden_city),
                golden_state,
                golden_zip,
                golden_address_last_seen,
                skip_trace_property.age,
                self.__get_is_deceased(skip_trace_property),
                skip_trace_property.bankruptcy,
                skip_trace_property.returned_foreclosure_date,
                skip_trace_property.returned_lien_date,
                skip_trace_property.returned_judgment_date,
                self.__proper_case(skip_trace_property.relative_1_first_name),
                self.__proper_case(skip_trace_property.relative_1_last_name),
                skip_trace_property.relative_1_phone1,
                skip_trace_property.relative_1_phone2,
                skip_trace_property.relative_1_phone3,
                self.__proper_case(skip_trace_property.relative_2_first_name),
                self.__proper_case(skip_trace_property.relative_2_last_name),
                skip_trace_property.relative_2_phone1,
                skip_trace_property.relative_2_phone2,
                skip_trace_property.relative_2_phone3,
                skip_trace_property.has_litigator,
                skip_trace_property.has_hit,
                self.__get_record_status(skip_trace_property),
            ]
            # Append to data_list (to be deprecated)
            self.data_list.append(current_record_values)

            # Create list of dict() with header values from `SkipTracePropertyRenderer` as keys
            current_record_dict = dict()
            for i, header in enumerate(SkipTracePropertyRenderer.header):
                current_record_dict[header] = current_record_values[i]

            self.data_dict.append(current_record_dict)

    @staticmethod
    def __get_validated_addresses(skip_trace_property):
        """
        Format validated returned address and mailing address with address lines 1 and 2.

        :param skip_trace_property: `SkipTraceProperty` object
        :return: Two strings: 1st is validated returned address, 2nd is validated mailing address.
        """
        returned_line_2 = f' {skip_trace_property.validated_returned_address_2}' \
            if skip_trace_property.validated_returned_address_2 else ''

        mailing_line_2 = f' {skip_trace_property.validated_mailing_delivery_line_2}' \
            if skip_trace_property.validated_mailing_delivery_line_2 else ''

        return f'{skip_trace_property.validated_returned_address_1}{returned_line_2}', \
               f'{skip_trace_property.validated_mailing_delivery_line_1}{mailing_line_2} '

    @staticmethod
    def __get_golden_address(skip_trace_property, validated_returned_address):
        """
        If the address returned from IDI is not the same as the mailing address, this is the
        "Golden Address".

        :param skip_trace_property: `SkipTraceProperty` object
        :param validated_returned_address: string from '__get_validated_addresses()'
        :return: golden_address, golden_city, golden_state, golden_zip, golden_address_last_seen
        """
        golden_address = ''
        golden_city = ''
        golden_state = ''
        golden_zip = ''
        golden_address_last_seen = ''

        can_check = \
            skip_trace_property.has_returned_address and skip_trace_property.has_mailing_submitted
        if not can_check:
            return golden_address, golden_city, golden_state, golden_zip, golden_address_last_seen

        # Priority to determine Golden Address: Check validated addresses first, then submitted.
        returned_prefix = 'validated_returned_' \
            if skip_trace_property.has_returned_address_validated else 'returned_'
        mailing_prefix = 'validated_mailing_' \
            if skip_trace_property.address_validated() else 'submitted_mailing_'
        address_suffix = 'delivery_line_1' if skip_trace_property.address_validated() else 'address'
        zip_suffix = 'zipcode' if skip_trace_property.address_validated() else 'zip'

        mailing_address = getattr(skip_trace_property, f'{mailing_prefix}{address_suffix}')
        mailing_zip = getattr(skip_trace_property, f'{mailing_prefix}{zip_suffix}')
        returned_address = getattr(skip_trace_property, f'{returned_prefix}address_1')
        returned_city = getattr(skip_trace_property, f'{returned_prefix}city_1')
        returned_state = getattr(skip_trace_property, f'{returned_prefix}state_1')
        returned_zip = getattr(skip_trace_property, f'{returned_prefix}zip_1')

        if mailing_address != returned_address and mailing_zip != returned_zip:
            golden_address = validated_returned_address \
                if skip_trace_property.has_returned_address_validated else returned_address
            golden_city = returned_city
            golden_state = returned_state
            golden_zip = returned_zip
            golden_address_last_seen = skip_trace_property.returned_address_last_seen_1

        return golden_address, golden_city, golden_state, golden_zip, golden_address_last_seen

    @staticmethod
    def __get_record_status(skip_trace_property):
        """
        Return whether record is existing or new (blank if no hit).

        :param skip_trace_property: `SkipTraceProperty` object
        :return: string 'existing', 'new', or blank
        """
        if not skip_trace_property.has_hit:
            record_status = ''
        elif skip_trace_property.is_existing_match:
            record_status = 'existing'
        else:
            record_status = 'new'
        return record_status

    @staticmethod
    def __get_is_deceased(skip_trace_property):
        """
        Translate value in 'is_deceased' from 'True' or 'False' (strings) to 'Yes' or 'No'.
        Otherwise, return blank string.

        :param skip_trace_property: `SkipTraceProperty` record
        :return: string 'Yes', 'No' or blank
        """
        if skip_trace_property.deceased == 'True':
            is_deceased = 'Yes'
        elif skip_trace_property.deceased == 'False':
            is_deceased = 'No'
        else:
            is_deceased = ''
        return is_deceased

    @staticmethod
    def __proper_case(val, title=True):
        """
        Proper case or return blank if val is None.
        :param val: string
        :param title: Boolean - if True title case. If False lowercase.
        """
        if not val:
            return ''
        if title:
            return val.title()
        return val.lower()
