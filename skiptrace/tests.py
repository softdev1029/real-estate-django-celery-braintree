import csv
from datetime import datetime, timedelta
import io
import json

from model_mommy import mommy

from django.core import mail
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone as django_tz

from billing.models import Transaction
from campaigns.tests import CampaignDataMixin
from companies.models import DownloadHistory
from sherpa.tests import BaseAPITestCase, BaseTestCase
from sherpa.utils import (
    get_data_from_column_mapping,
    get_upload_additional_cost,
)
from .models import SkipTraceProperty, UploadSkipTrace
from .resources import SkipTraceResource
from .skiptrace import (
    ProcessSkipTraceRecord,
    ProcessSkipTraceUpload,
    UpdateFromIDI,
)
from .tasks import (
    send_skip_trace_error_upload_email_task,
    skip_trace_push_to_campaign_task,
)

client = Client()


class SkipTraceDataMixin:
    """
    Create data needed for skip trace tests.
    """
    def setUp(self):
        super(SkipTraceDataMixin, self).setUp()
        # Create a `Property` object to assign to all `SkipTraceProperty`objects. `Property` is
        # being created and assigned in the smarty streets validation code, but we can't do that in
        # test.
        address = mommy.make("properties.Address")
        self.prop = mommy.make("properties.Property", address=address, company=self.company1)
        self.skip_trace = mommy.make("sherpa.UploadSkipTrace", company=self.company1)
        self.skip_trace_property1 = mommy.make(
            "sherpa.SkipTraceProperty",
            upload_skip_trace=self.skip_trace,
            returned_phone_1=2222222222,
            returned_phone_2=3333333333,
            returned_phone_3=4444444444,
            prop=self.prop,
        )
        self.skip_trace_property2 = mommy.make(
            "sherpa.SkipTraceProperty",
            returned_phone_1=5555555555,
            returned_phone_2=6666666666,
            returned_phone_3=7777777777,
            prop=self.prop,
        )
        self.campaign = mommy.make("sherpa.Campaign", company=self.company1)

        self.process_upload = ProcessSkipTraceUpload(self.skip_trace)
        self.process_skip_trace_record = ProcessSkipTraceRecord(
            self.skip_trace_property1, self.skip_trace)
        self.upload_from_idi = UpdateFromIDI(self.skip_trace, self.skip_trace_property1)
        self.prospect = mommy.make("sherpa.Prospect")


@override_settings(task_always_eager=False)
class SkipTraceUploadTestCase(SkipTraceDataMixin, CampaignDataMixin, BaseTestCase):
    def __map_skip_trace(self, column_fields):
        update_fields = []
        for i, field in enumerate(column_fields):
            setattr(self.skip_trace, f'{field}_column_number', i)
            update_fields.append(f'{field}_column_number')
        self.skip_trace.save(update_fields=update_fields)

    def test_wrong_number_change(self):
        self.prospect_wrong_number = mommy.make(
            'sherpa.Prospect',
            first_name='Master',
            last_name='Chief',
            company=self.company1,
            phone_raw='1234560123',
            property_address='123 Blood Gulch',
            property_city='Halo Ring 123',
            property_state='TX',
            property_zip='12345',
            wrong_number=True,
        )
        self.wrong_number_upload_trace = mommy.make(
            'sherpa.UploadSkipTrace',
            company=self.company1,
            push_to_campaign_campaign_id=self.george_campaign.id,
        )
        self.wrong_number_trace_property = mommy.make(
            'sherpa.SkipTraceProperty',
            returned_phone_1='1234560123',
            submitted_owner_first_name='Different',
            submitted_owner_last_name='Name',
            validated_property_status='validated',
            validated_property_delivery_line_1='Line 1',
            validated_property_delivery_line_2='Line 2',
            validated_property_city_name='Different City',
            validated_property_state_abbreviation='NY',
            validated_property_zipcode=12345,
            submitted_mailing_address='Mail Addresss',
            submitted_mailing_city='Mail City',
            upload_skip_trace=self.wrong_number_upload_trace,
            prop=self.prop,
        )
        self.assertTrue(self.prospect_wrong_number.wrong_number)
        skip_trace_push_to_campaign_task(self.wrong_number_upload_trace.id)
        self.prospect_wrong_number.refresh_from_db()
        self.assertFalse(self.prospect_wrong_number.wrong_number)

    def test_skip_trace_phone_list(self):
        phone_numbers = ['2222222222', '3434343434', '5656565656']
        self.skip_trace_property1.returned_phone_1 = phone_numbers[0]
        self.skip_trace_property1.returned_phone_2 = phone_numbers[1]
        self.skip_trace_property1.returned_phone_3 = phone_numbers[2]
        self.skip_trace_property1.save(
            update_fields=[
                'returned_phone_1',
                'returned_phone_2',
                'returned_phone_3',
            ],
        )

        self.assertListEqual(phone_numbers, self.skip_trace_property1.phone_list)
        self.assertFalse(4444444444 in self.skip_trace_property1.phone_list)

    def test_skip_trace_has_litigator(self):
        litigator = mommy.make("sherpa.LitigatorList", phone=9999999, type='Litigator')
        litigator.phone = self.skip_trace_property1.returned_phone_2
        litigator.save(update_fields=['phone'])

        self.assertTrue(self.skip_trace_property1.has_litigator)
        self.assertFalse(self.skip_trace_property2.has_litigator)

        litigator.phone = self.skip_trace_property2.returned_phone_3
        litigator.save(update_fields=['phone'])

        self.assertTrue(self.skip_trace_property2.has_litigator)
        self.assertFalse(self.skip_trace_property1.has_litigator)

    def test_skip_trace_total_litigators(self):
        litigator = mommy.make("sherpa.LitigatorList", phone=9999999, type='Litigator')
        litigator.phone = self.skip_trace_property1.returned_phone_1
        litigator.save(update_fields=['phone'])

        if self.skip_trace_property1.has_litigator:
            self.skip_trace.total_litigators += 1

        if self.skip_trace_property2.has_litigator:
            self.skip_trace.total_litigators += 1

        self.skip_trace.save(update_fields=['total_litigators'])

        self.assertTrue(self.skip_trace_property1.has_litigator)
        self.assertFalse(self.skip_trace_property2.has_litigator)
        self.assertEqual(self.skip_trace.total_litigators, 1)

    def test_upload_skip_trace_rows_to_push_to_campaign(self):
        self.skip_trace_property1.upload_skip_trace = self.skip_trace
        self.skip_trace_property1.save(update_fields=['upload_skip_trace'])

        self.assertEqual(self.skip_trace.rows_to_push_to_campaign(), 1)

        self.skip_trace_property2.upload_skip_trace = self.skip_trace
        self.skip_trace_property2.existing_match_prospect_id = 1
        self.skip_trace_property2.save(
            update_fields=[
                'existing_match_prospect_id',
                'upload_skip_trace',
            ],
        )
        self.assertEqual(self.skip_trace.rows_to_push_to_campaign(), 2)
        self.assertEqual(self.skip_trace.rows_to_push_to_campaign('new'), 1)

    def test_upload_skip_trace_authorize_transaction(self):
        self.skip_trace.company = self.company1
        self.skip_trace.save(update_fields=['company'])
        transaction_authorized = self.skip_trace.authorize_transaction(10)

        # Test the skip trace transaction without push to campaign.
        self.assertTrue(transaction_authorized)
        self.assertEqual(self.skip_trace.transaction.company, self.skip_trace.company)
        self.assertEqual(self.skip_trace.transaction.description, 'Sherpa Skip Trace Fee')
        self.assertEqual(self.skip_trace.transaction.type, Transaction.Type.SKIP_TRACE)
        self.assertEqual(self.skip_trace.transaction.amount_authorized, 10)

        # Test when pushing to campaign.
        transaction_authorized = self.skip_trace.authorize_transaction(5, push_to_campaign=True)
        self.assertTrue(transaction_authorized)
        self.assertEqual(self.skip_trace.push_to_campaign_transaction.company,
                         self.skip_trace.company)
        self.assertEqual(self.skip_trace.push_to_campaign_transaction.description,
                         'Sherpa Upload Fee')
        self.assertEqual(self.skip_trace.push_to_campaign_transaction.type,
                         Transaction.Type.UPLOAD)
        self.assertEqual(self.skip_trace.push_to_campaign_transaction.amount_authorized, 5)

    def test_charge_upload_skip_trace_for_additional_rows(self):
        # Create objects needed for this test
        self.company_exceeds_monthly = mommy.make(
            'sherpa.Company',
            name='Exceeds Monthly Company',
            invitation_code=self.invitation_code1,
            subscription_id='gh3mcb',
            monthly_upload_limit=4,
            cost_per_upload=.75,
        )
        self.skip_trace_exceeds_monthly = mommy.make(
            "sherpa.UploadSkipTrace",
            company=self.company_exceeds_monthly,
        )
        self.campaign_exceeds_monthy = mommy.make(
            "sherpa.Campaign",
            company=self.company_exceeds_monthly,
        )

        for i in range(5):
            mommy.make(
                "sherpa.SkipTraceProperty",
                upload_skip_trace=self.skip_trace_exceeds_monthly,
                returned_phone_1=2222222222,
            )

        cost, exceeds_count = get_upload_additional_cost(
            self.company_exceeds_monthly,
            self.skip_trace_exceeds_monthly.rows_to_push_to_campaign(),
            self.skip_trace_exceeds_monthly,
        )

        self.assertTrue(self.skip_trace_exceeds_monthly.authorize_transaction(
            cost, push_to_campaign=True))
        self.assertEqual(exceeds_count, 1)
        self.assertEqual(cost, 1.00)
        self.assertEqual(
            self.skip_trace_exceeds_monthly.push_to_campaign_transaction.amount_authorized,
            cost)

        self.company_exceeds_monthly.monthly_upload_limit = 3
        self.company_exceeds_monthly.save(update_fields=['monthly_upload_limit'])
        cost, exceeds_count = get_upload_additional_cost(
            self.company_exceeds_monthly,
            self.skip_trace_exceeds_monthly.rows_to_push_to_campaign(),
            self.skip_trace_exceeds_monthly,
        )

        self.assertTrue(self.skip_trace_exceeds_monthly.authorize_transaction(
            cost, push_to_campaign=True))
        self.assertEqual(exceeds_count, 2)
        self.assertEqual(cost, exceeds_count * self.company_exceeds_monthly.cost_per_upload)
        self.assertEqual(
            self.skip_trace_exceeds_monthly.push_to_campaign_transaction.amount_authorized,
            cost)

    def test_debit_skip_trace_balance(self):
        self.company1.sherpa_balance = 0
        self.company1.save(update_fields=['sherpa_balance'])
        error = self.company1.debit_sherpa_balance(1)
        self.assertEqual(error, 'insufficient balance')

        self.company1.credit_sherpa_balance(40)

        error = self.company1.debit_sherpa_balance(1)
        self.assertEqual(error, None)
        self.assertEqual(self.company1.sherpa_balance, 39)

    def test_create_single_upload_skip_trace(self):
        upload_skip_trace = UploadSkipTrace.create_new(self.george_user, 1, has_header=False)

        self.assertTrue(upload_skip_trace.is_single_upload)
        self.assertFalse(upload_skip_trace.has_header_row)

    def test_save_skip_trace_from_form(self):
        form_data = {
            'property_address': '123 Property Address',
            'property_city': 'Property City',
            'property_state': 'Property State',
            'property_zip': 12345,
            'property_only': 'on',
        }
        skip_trace_property, error = SkipTraceProperty().save_from_single_upload_form(
            form_data, self.george_user)

        self.assertIsNone(error)
        self.assertEqual(skip_trace_property.submitted_property_address,
                         form_data['property_address'])
        self.assertEqual(skip_trace_property.submitted_property_city,
                         form_data['property_city'])
        self.assertEqual(skip_trace_property.submitted_property_state,
                         form_data['property_state'])
        self.assertEqual(skip_trace_property.submitted_property_zip,
                         form_data['property_zip'])

        form_data = {
            'property_address': '122 Property Address',
            'property_city': 'Propertyville',
            'property_state': 'Prop State',
            'property_zip': 12347,
            'mailing_address': '123 Mailing Address',
            'mailing_city': 'Mailing City',
            'mailing_state': 'Mailing State',
            'mailing_zip': 12345,
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'property_only': False,
        }
        skip_trace_property, error = SkipTraceProperty().save_from_single_upload_form(
            form_data, self.george_user)

        self.assertIsNone(error)
        self.assertEqual(skip_trace_property.submitted_owner_fullname,
                         f'{form_data["first_name"]} {form_data["last_name"]}')
        self.assertEqual(skip_trace_property.submitted_owner_first_name,
                         form_data['first_name'])
        self.assertEqual(skip_trace_property.submitted_owner_last_name,
                         form_data['last_name'])
        self.assertEqual(skip_trace_property.submitted_property_address,
                         form_data['property_address'])
        self.assertEqual(skip_trace_property.submitted_property_city,
                         form_data['property_city'])
        self.assertEqual(skip_trace_property.submitted_property_state,
                         form_data['property_state'])
        self.assertEqual(skip_trace_property.submitted_property_zip,
                         form_data['property_zip'])
        self.assertEqual(skip_trace_property.submitted_mailing_address,
                         form_data['mailing_address'])
        self.assertEqual(skip_trace_property.submitted_mailing_city,
                         form_data['mailing_city'])
        self.assertEqual(skip_trace_property.submitted_mailing_state,
                         form_data['mailing_state'])
        self.assertEqual(skip_trace_property.submitted_mailing_zip,
                         form_data['mailing_zip'])

    def test_skip_trace_property_address_validated(self):

        def check_all(valid):
            is_property_status = [False, True]
            for i, status in enumerate(is_property_status):
                self.assertEqual(self.skip_trace_property1.address_validated(status), valid[i])
        both_false = [False, False]
        mailing_true = [True, False]
        property_true = [False, True]
        both_true = [True, True]

        self.skip_trace_property1.validated_property_status = 'invalid'
        self.skip_trace_property1.validated_mailing_status = 'invalid'
        self.skip_trace_property1.save(
            update_fields=['validated_property_status', 'validated_mailing_status'])
        check_all(both_false)

        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.save(update_fields=['validated_property_status'])
        check_all(both_false)
        self.skip_trace_property1.validated_mailing_status = 'validated'
        self.skip_trace_property1.save(update_fields=['validated_mailing_status'])
        check_all(both_false)

        self.skip_trace_property1.validated_property_delivery_line_1 = 'abcdefg'
        self.skip_trace_property1.save(update_fields=['validated_property_delivery_line_1'])
        check_all(both_false)
        self.skip_trace_property1.validated_mailing_delivery_line_1 = 'abcdefg'
        self.skip_trace_property1.save(update_fields=['validated_mailing_delivery_line_1'])
        check_all(both_false)

        self.skip_trace_property1.validated_property_zipcode = 12345
        self.skip_trace_property1.save(update_fields=['validated_property_zipcode'])
        check_all(property_true)
        self.skip_trace_property1.validated_mailing_zipcode = 12345
        self.skip_trace_property1.save(update_fields=['validated_mailing_zipcode'])
        check_all(both_true)

        self.skip_trace_property1.validated_property_status = 'something'
        self.skip_trace_property1.save(update_fields=['validated_property_status'])
        check_all(mailing_true)

    def test_has_valid_idi_token(self):
        self.assertFalse(self.skip_trace.has_valid_idi_token)
        self.skip_trace.idi_token = 'abcdef'
        self.skip_trace.save(update_fields=['idi_token'])
        self.assertTrue(self.skip_trace.has_valid_idi_token)
        self.skip_trace.last_idi_token_reset = django_tz.now()
        self.skip_trace.save(update_fields=['last_idi_token_reset'])
        self.assertTrue(self.skip_trace.has_valid_idi_token)
        self.skip_trace.last_idi_token_reset = django_tz.now() - timedelta(seconds=1501)
        self.skip_trace.save(update_fields=['last_idi_token_reset'])
        self.assertFalse(self.skip_trace.has_valid_idi_token)

    def test_continue_processing_row(self):
        self.process_upload.initialize_upload()
        self.assertEqual(self.skip_trace.status, 'running')
        self.assertTrue(self.skip_trace.upload_start is not None)
        self.assertFalse(self.skip_trace.stop_upload)
        self.skip_trace.has_header_row = False
        self.skip_trace.save(update_fields=['has_header_row'])
        self.assertEqual(self.process_upload.continue_processing_row(),
                         self.process_upload.CONTINUE)
        self.skip_trace.has_header_row = True
        self.skip_trace.save(update_fields=['has_header_row'])
        self.assertEqual(self.process_upload.continue_processing_row(), self.process_upload.SKIP)
        self.process_upload.increment_last_row_processed()
        self.assertEqual(self.process_upload.continue_processing_row(),
                         self.process_upload.CONTINUE)
        self.skip_trace.stop_upload = True
        self.skip_trace.save(update_fields=['stop_upload'])
        self.assertEqual(self.process_upload.continue_processing_row(), self.process_upload.STOP)

    def test_get_data_from_column_mapping(self):
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
        self.__map_skip_trace(column_fields)

        row = column_fields.copy()
        row[0] = 'first last'

        address_data = get_data_from_column_mapping(column_fields, row, self.skip_trace)
        self.assertEqual(address_data['fullname'], 'First Last')
        self.assertEqual(address_data['first_name'], 'First')
        self.assertEqual(address_data['last_name'], 'Last')
        self.assertEqual(address_data['property_street'], 'property_street')
        for i, val in enumerate(row[3:]):
            index = i + 3
            self.assertEqual(address_data[column_fields[index]], column_fields[index])

        row[0] = ''
        address_data = get_data_from_column_mapping(column_fields, row, self.skip_trace)
        self.assertEqual((address_data['fullname']), 'First_Name Last_Name')

        # If we're missing data we can't guarantee the column mapping is correct.
        # This should return None so we don't process bad data. This is due to what
        # happens in FlatFile when uploading a .xlsx file with blank data in the last
        # columns.
        row2 = row[:5]
        address_data = get_data_from_column_mapping(column_fields, row2, self.skip_trace)
        self.assertIsNone(address_data)

    def test_process_records_from_csv_batch(self):
        column_fields = [
            'property_street',
            'property_city',
            'property_state',
            'property_zipcode',
        ]
        self.__map_skip_trace(column_fields)

        # Include one row of bad data. Should be processed but not a hit.
        batch = [
            [
                '123 Fake St',
                'Fakeville',
                'TX',
                '12345',
            ],
            [
                '125 Fake St',
                'Fakeville',
                'TX',
            ],
            [
                '127 Fake St',
                'Fakeville',
                'TX',
                '12345',
            ],
        ]
        address = mommy.make(
            'properties.Address',
            address='123 Fake St Fakeville',
            city='Schenectady',
            state='NY',
            zip_code='12345',
        )
        prop = mommy.make(
            'properties.Property',
            company_id=self.company1.id,
            address=address,
        )
        property_tag = self.george_user.profile.company.propertytag_set.first()
        prop.tags.add(property_tag)
        self.skip_trace.property_tags.add(property_tag)
        self.process_upload.process_records_from_csv_batch(batch)
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.last_row_processed, 3)
        self.assertEqual(self.skip_trace.total_hits, 2)
        prop = self.skip_trace.skiptraceproperty_set.filter(has_hit=True).first().prop
        self.assertIn(property_tag, prop.tags.all())

    def test_get_matching_skip_trace_properties(self):
        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.save(update_fields=['validated_property_status'])
        matches = self.process_skip_trace_record.get_matching_skip_trace_properties()
        self.assertEqual(len(matches), 0)

        self.skip_trace_property2.validated_property_status = 'validated'
        self.skip_trace_property2.has_hit = True
        delivery_line1 = 'abcdefg'
        zip_code = 12345
        self.skip_trace_property2.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property2.validated_property_zipcode = zip_code
        self.skip_trace_property1.validated_property_zipcode = zip_code
        update_fields = [
            'has_hit',
            'validated_property_status',
            'validated_property_delivery_line_1',
            'validated_property_zipcode',
        ]
        for obj in [self.skip_trace_property1, self.skip_trace_property2]:
            obj.save(update_fields=update_fields)

        matches = self.process_skip_trace_record.get_matching_skip_trace_properties()
        self.assertEqual(len(matches), 1)
        self.skip_trace_property1.validated_mailing_status = 'validated'
        self.skip_trace_property1.save(update_fields=['validated_mailing_status'])
        self.skip_trace_property2.validated_mailing_status = 'validated'
        self.skip_trace_property2.validated_mailing_delivery_line_1 = delivery_line1
        self.skip_trace_property1.validated_mailing_delivery_line_1 = delivery_line1
        self.skip_trace_property2.validated_mailing_zipcode = zip_code
        self.skip_trace_property1.validated_mailing_zipcode = zip_code
        for obj in [self.skip_trace_property1, self.skip_trace_property2]:
            obj.save(update_fields=update_fields)
        matches = self.process_skip_trace_record.get_matching_skip_trace_properties()
        self.assertEqual(len(matches), 1)

    def test_get_matching_prospects(self):
        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.validated_property_delivery_line_1 = \
            f"{self.prospect.property_address}1"
        self.skip_trace_property1.save(update_fields=[
            'validated_property_status',
            'validated_property_delivery_line_1',
        ])
        matches = self.process_skip_trace_record.get_matching_prospects()
        self.assertEqual(len(matches), 0)

        self.prospect.company = self.skip_trace_property1.upload_skip_trace.company
        self.prospect.validated_property_status = 'validated'
        delivery_line1 = 'abcdefg'
        zip_code = 12345
        self.prospect.property_address = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.prospect.property_zip = zip_code
        self.skip_trace_property1.validated_property_zipcode = zip_code
        update_fields = [
            {
                'obj': self.skip_trace_property1,
                'fields': [
                    'validated_property_status',
                    'validated_property_delivery_line_1',
                    'validated_property_delivery_line_2',
                    'validated_property_zipcode',
                ],
            },
            {
                'obj': self.prospect,
                'fields': [
                    'company',
                    'validated_property_status',
                    'property_address',
                    'property_zip',
                ],
            },
        ]
        for data in update_fields:
            data['obj'].save(update_fields=data['fields'])

        matches = self.process_skip_trace_record.get_matching_prospects()
        self.assertEqual(len(matches), 1)

    def test_copy_missing_name(self):
        copied = self.process_skip_trace_record.copy_missing_name(
            [self.skip_trace_property2], match_is_skip_trace=True)
        self.assertFalse(copied)

        self.skip_trace_property2.submitted_owner_fullname = 'First Last'
        self.skip_trace_property2.submitted_owner_first_name = 'First'
        self.skip_trace_property2.submitted_owner_last_name = 'Last'
        self.skip_trace_property2.save(
            update_fields=[
                'submitted_owner_fullname',
                'submitted_owner_first_name',
                'submitted_owner_last_name',
            ],
        )

        copied = self.process_skip_trace_record.copy_missing_name(
            [self.skip_trace_property2], match_is_skip_trace=True)
        self.assertTrue(copied)
        self.assertEqual(
            self.skip_trace_property2.submitted_owner_fullname,
            self.skip_trace_property1.submitted_owner_fullname,
        )

        copied = self.process_skip_trace_record.copy_missing_name([self.prospect])
        self.assertTrue(copied)

        self.skip_trace_property1.submitted_owner_first_name = ''
        self.skip_trace_property1.submitted_owner_last_name = ''
        self.skip_trace_property1.save(
            update_fields=[
                'submitted_owner_first_name',
                'submitted_owner_last_name',
            ],
        )

        copied = self.process_skip_trace_record.copy_missing_name([self.prospect])
        self.assertFalse(copied)

        self.prospect.first_name = 'Full'
        self.prospect.last_name = 'Name'
        self.prospect.save(update_fields=['first_name', 'last_name'])
        copied = self.process_skip_trace_record.copy_missing_name([self.prospect])
        self.assertTrue(copied)
        self.assertEqual(
            self.skip_trace_property1.submitted_owner_fullname,
            self.prospect.get_full_name(),
        )

    def test_copy_missing_mailing_address(self):
        self.process_skip_trace_record.copy_missing_mailing_address(
            [self.skip_trace_property2], match_is_skip_trace=True)
        self.assertEqual(self.skip_trace_property1.submitted_mailing_address, None)

        self.skip_trace_property2.submitted_mailing_address = 'abcdefg'
        self.skip_trace_property2.save(update_fields=['submitted_mailing_address'])
        self.process_skip_trace_record.copy_missing_mailing_address(
            [self.skip_trace_property2], match_is_skip_trace=True)
        self.assertEqual(self.skip_trace_property1.submitted_mailing_address, 'abcdefg')

        self.prospect.mailing_address = 'hijklmno'
        self.prospect.save(update_fields=['mailing_address'])
        self.skip_trace_property1.submitted_mailing_address = ''
        self.skip_trace_property1.save(update_fields=['submitted_mailing_address'])

        self.process_skip_trace_record.copy_missing_mailing_address([self.prospect])
        self.assertEqual(self.skip_trace_property1.submitted_mailing_address, 'hijklmno')

    def test_update_hit_stats(self):
        self.skip_trace_property1.returned_phone_1 = None
        self.skip_trace_property1.save(update_fields=['returned_phone_1'])
        self.process_skip_trace_record.update_hit_stats()
        self.assertEqual(self.skip_trace.total_hits, 0)
        self.assertEqual(self.skip_trace.total_existing_matches, 0)
        self.assertEqual(self.skip_trace.total_billable_hits, 0)
        self.assertFalse(self.skip_trace_property1.has_hit)

        self.skip_trace_property1.returned_phone_1 = 2222222222
        self.skip_trace_property1.returned_phone_2 = 3333333333
        self.skip_trace_property1.returned_phone_3 = 4444444444
        self.skip_trace_property1.returned_phone_4 = 5555555555
        self.skip_trace_property1.returned_email_1 = 'testemail@email.com'
        self.skip_trace_property1.returned_email_2 = 'testemail2@email.com'
        self.skip_trace_property1.returned_email_3 = 'testemail3@email.com'
        self.skip_trace_property1.returned_address_1 = 'abcdefg'
        self.skip_trace_property1.save(
            update_fields=[
                'returned_phone_1',
                'returned_phone_2',
                'returned_phone_3',
                'returned_phone_4',
                'returned_email_1',
                'returned_email_2',
                'returned_email_3',
                'returned_address_1',
            ],
        )

        self.skip_trace.total_phone = 0
        self.skip_trace.total_email = 0
        self.skip_trace.total_addresses = 0
        self.skip_trace.save(update_fields=['total_phone', 'total_email', 'total_addresses'])
        self.process_skip_trace_record.update_hit_stats()

        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.total_hits, 1)
        self.assertEqual(self.skip_trace.total_billable_hits, 1)
        self.assertTrue(self.skip_trace_property1.has_hit)
        self.assertEqual(self.skip_trace.total_phone, 3)
        self.assertEqual(self.skip_trace.total_email, 2)
        self.assertEqual(self.skip_trace.total_addresses, 1)
        self.assertEqual(self.skip_trace.total_existing_matches, 0)

        self.process_skip_trace_record.update_hit_stats(copy_from_existing=True)
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.total_existing_matches, 1)
        self.assertEqual(self.skip_trace.total_hits, 2)
        self.assertEqual(self.skip_trace.total_billable_hits, 1)
        self.assertTrue(self.skip_trace_property1.has_hit)
        self.assertEqual(self.skip_trace.total_phone, 6)
        self.assertEqual(self.skip_trace.total_email, 4)
        self.assertEqual(self.skip_trace.total_addresses, 2)

    def test_copy_from_match(self):
        copied = self.process_skip_trace_record.copy_from_match()
        self.assertFalse(copied)
        self.assertEqual(self.skip_trace.total_existing_matches, 0)

        self.prospect.company = self.skip_trace_property1.upload_skip_trace.company
        self.prospect.validated_property_status = 'validated'
        self.skip_trace_property1.validated_property_status = 'validated'
        delivery_line1 = 'abcdefg'
        zip_code = 12345
        self.prospect.property_address = f"{delivery_line1} {delivery_line1}"
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.prospect.validated_property_delivery_line_2 = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_2 = delivery_line1
        self.prospect.property_zip = zip_code
        self.skip_trace_property1.validated_property_zipcode = zip_code
        self.prospect.first_name = 'first'
        self.prospect.last_name = 'last'
        update_fields = [
            {
                'obj': self.skip_trace_property1,
                'fields': [
                    'validated_property_status',
                    'validated_property_delivery_line_1',
                    'validated_property_delivery_line_2',
                    'validated_property_zipcode',
                ],
            },
            {
                'obj': self.prospect,
                'fields': [
                    'company',
                    'validated_property_status',
                    'property_address',
                    'property_zip',
                    'first_name',
                    'last_name',
                ],
            },
        ]
        for data in update_fields:
            data['obj'].save(update_fields=data['fields'])

        copied = self.process_skip_trace_record.copy_from_match()
        self.skip_trace.refresh_from_db()
        self.assertTrue(copied)
        self.assertEqual(self.skip_trace.total_existing_matches, 1)
        self.assertEqual(self.skip_trace_property1.validated_property_delivery_line_1, 'abcdefg')
        self.assertTrue(self.skip_trace_property1.is_existing_match)

        self.skip_trace.total_existing_matches = 0
        self.skip_trace.save(update_fields=['total_existing_matches'])

        self.skip_trace_property2.validated_property_status = 'validated'
        self.skip_trace_property2.upload_skip_trace = self.skip_trace
        self.skip_trace_property1.validated_mailing_status = 'invalid'
        self.skip_trace_property2.has_hit = True
        delivery_line1 = 'hijklmno'
        zip_code = 12345
        self.skip_trace_property2.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property2.validated_property_delivery_line_2 = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_2 = delivery_line1
        self.skip_trace_property2.validated_property_zipcode = zip_code
        self.skip_trace_property1.validated_property_zipcode = zip_code
        self.skip_trace_property2.submitted_owner_first_name = 'first'
        update_fields = [
            'has_hit',
            'upload_skip_trace',
            'validated_property_status',
            'validated_mailing_status',
            'validated_property_delivery_line_1',
            'validated_property_delivery_line_2',
            'validated_property_zipcode',
            'submitted_owner_first_name',
        ]
        for obj in [self.skip_trace_property1, self.skip_trace_property2]:
            obj.save(update_fields=update_fields)

        copied = self.process_skip_trace_record.copy_from_match()
        self.skip_trace.refresh_from_db()
        self.assertTrue(copied)
        self.assertEqual(self.skip_trace.total_existing_matches, 1)
        self.assertEqual(self.skip_trace_property1.validated_property_delivery_line_1, 'hijklmno')

    def test_upload_from_idi_format_search_criteria(self):
        self.skip_trace_property1.submitted_property_address = 'submitted property address'
        self.skip_trace_property1.submitted_property_city = 'city1'
        self.skip_trace_property1.submitted_property_state = 'state1'
        self.skip_trace_property1.submitted_property_zip = 12341

        self.skip_trace_property1.submitted_owner_first_name = 'First A'
        self.skip_trace_property1.submitted_owner_last_name = "Last"
        self.skip_trace_property1.save(
            update_fields=[
                'submitted_property_address',
                'submitted_owner_first_name',
                'submitted_owner_last_name',
                'submitted_property_city',
                'submitted_property_state',
                'submitted_property_zip',
            ],
        )
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertEqual(
            search_criteria['address'], self.skip_trace_property1.submitted_property_address)
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.submitted_property_city)
        self.assertEqual(
            search_criteria['state'], self.skip_trace_property1.submitted_property_state)
        self.assertEqual(search_criteria['zip'], self.skip_trace_property1.submitted_property_zip)

        self.skip_trace_property1.submitted_mailing_address = 'submitted mailing address'
        self.skip_trace_property1.submitted_mailing_city = 'city2'
        self.skip_trace_property1.submitted_mailing_state = 'state2'
        self.skip_trace_property1.submitted_mailing_zip = 12342

        self.skip_trace_property1.save(
            update_fields=[
                'submitted_mailing_address',
                'submitted_mailing_city',
                'submitted_mailing_state',
                'submitted_mailing_zip',
            ],
        )
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertEqual(
            search_criteria['address'], self.skip_trace_property1.submitted_mailing_address)
        self.assertEqual(search_criteria['city'], self.skip_trace_property1.submitted_mailing_city)
        self.assertEqual(
            search_criteria['state'], self.skip_trace_property1.submitted_mailing_state)
        self.assertEqual(search_criteria['zip'], self.skip_trace_property1.submitted_mailing_zip)

        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.validated_property_delivery_line_1 = 'validated property address'
        self.skip_trace_property1.validated_property_delivery_line_2 = 'line2'
        self.skip_trace_property1.validated_property_city_name = 'city3'
        self.skip_trace_property1.validated_property_state_abbreviation = 'state3'
        self.skip_trace_property1.validated_property_zipcode = 12343
        update_fields = [
            'validated_property_status',
            'validated_property_delivery_line_1',
            'validated_property_delivery_line_2',
            'validated_property_city_name',
            'validated_property_state_abbreviation',
            'validated_property_zipcode',
        ]
        self.skip_trace_property1.save(update_fields=update_fields)

        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertEqual(
            search_criteria['address'],
            f'{self.skip_trace_property1.validated_property_delivery_line_1} line2',
        )
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.validated_property_city_name)
        self.assertEqual(
            search_criteria['state'],
            self.skip_trace_property1.validated_property_state_abbreviation,
        )
        self.assertEqual(
            search_criteria['zip'], self.skip_trace_property1.validated_property_zipcode)

        self.skip_trace_property1.validated_mailing_status = 'validated'
        self.skip_trace_property1.validated_mailing_delivery_line_1 = 'validated mailing address'
        self.skip_trace_property1.validated_mailing_city_name = 'city4'
        self.skip_trace_property1.validated_mailing_state_abbreviation = 'state4'
        self.skip_trace_property1.validated_mailing_zipcode = 12344
        update_fields = [
            'validated_mailing_status',
            'validated_mailing_delivery_line_1',
            'validated_mailing_city_name',
            'validated_mailing_state_abbreviation',
            'validated_mailing_zipcode',
        ]
        self.skip_trace_property1.save(update_fields=update_fields)
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertEqual(
            search_criteria['lastName'], self.skip_trace_property1.submitted_owner_last_name)
        self.assertEqual(
            search_criteria['firstName'], 'First')
        self.assertEqual(
            search_criteria['address'],
            self.skip_trace_property1.validated_mailing_delivery_line_1,
        )
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.validated_mailing_city_name)
        self.assertEqual(
            search_criteria['state'],
            self.skip_trace_property1.validated_mailing_state_abbreviation,
        )
        self.assertEqual(
            search_criteria['zip'], self.skip_trace_property1.validated_mailing_zipcode)
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertEqual(
            search_criteria['address'],
            self.skip_trace_property1.validated_mailing_delivery_line_1,
        )
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.validated_mailing_city_name)
        self.assertEqual(
            search_criteria['state'],
            self.skip_trace_property1.validated_mailing_state_abbreviation,
        )
        self.assertEqual(
            search_criteria['zip'], self.skip_trace_property1.validated_mailing_zipcode)

        # Check property for mailing only search
        self.upload_from_idi.mailing_only_search = True
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertTrue('firstName' not in search_criteria)
        self.assertTrue('lastName' not in search_criteria)
        self.assertEqual(
            search_criteria['address'],
            f'{self.skip_trace_property1.validated_mailing_delivery_line_1}',
        )
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.validated_mailing_city_name)
        self.assertEqual(
            search_criteria['state'],
            self.skip_trace_property1.validated_mailing_state_abbreviation,
        )
        self.assertEqual(
            search_criteria['zip'], self.skip_trace_property1.validated_mailing_zipcode)

        # Check criteria for property only search
        self.upload_from_idi.mailing_only_search = False
        self.upload_from_idi.property_only_search = True
        search_criteria = self.upload_from_idi.format_search_criteria()
        self.assertTrue('firstName' not in search_criteria)
        self.assertTrue('lastName' not in search_criteria)
        self.assertEqual(
            search_criteria['address'],
            f'{self.skip_trace_property1.validated_property_delivery_line_1} line2',
        )
        self.assertEqual(
            search_criteria['city'], self.skip_trace_property1.validated_property_city_name)
        self.assertEqual(
            search_criteria['state'],
            self.skip_trace_property1.validated_property_state_abbreviation,
        )
        self.assertEqual(
            search_criteria['zip'], self.skip_trace_property1.validated_property_zipcode)

    def test_upload_from_idi_set_skip_trace_status(self):
        self.skip_trace.idi_token = 'test token'
        self.skip_trace.save(update_fields=['idi_token'])
        self.upload_from_idi.set_skip_trace_status('test status')

        self.assertEqual(self.skip_trace_property1.skip_trace_status, 'test status')
        self.assertEqual(self.skip_trace.idi_token, 'test token')

    def test_get_name_from_idi(self):
        result = {'name': [{'first': 'First', 'last': 'Last', 'data': 'First Last'}]}
        self.upload_from_idi.get_name_from_idi(result)

        self.assertEqual(self.skip_trace_property1.submitted_owner_first_name, 'First')
        self.assertEqual(self.skip_trace_property1.submitted_owner_last_name, 'Last')
        self.assertEqual(self.skip_trace_property1.submitted_owner_fullname, 'First Last')
        self.assertEqual(self.skip_trace_property1.returned_first_name, 'First')
        self.assertEqual(self.skip_trace_property1.returned_last_name, 'Last')
        self.assertEqual(self.skip_trace_property1.returned_fullname, 'First Last')

    def test_get_phone_numbers_from_idi(self):
        phone = [
            {
                'number': 8888888888,
                'type': 'Residential',
                'disconnected': False,
                'providerName': 'Provider',
                'meta': {'lastSeen': '20190101'},
            },
        ]
        self.upload_from_idi.get_phone_numbers_from_idi(phone)
        self.assertEqual(self.skip_trace_property1.returned_phone_1, '8888888888')
        self.assertEqual(self.skip_trace_property1.returned_phone_type_1, 'Landline')
        self.assertFalse(self.skip_trace_property1.returned_phone_is_disconnected_1)
        self.assertEqual(self.skip_trace_property1.returned_phone_carrier_1, 'Provider')
        self.assertEqual(
            self.skip_trace_property1.returned_phone_last_seen_1, datetime(2019, 1, 1).date())

    def test_get_emails_from_idi(self):
        email = [{'data': 'email@email.com', 'meta': {'lastSeen': '20190101'}}]
        self.upload_from_idi.get_emails_from_idi(email)
        self.assertEqual(self.skip_trace_property1.returned_email_1, 'email@email.com')
        self.assertEqual(
            self.skip_trace_property1.returned_email_last_seen_1, datetime(2019, 1, 1).date())

    def test_get_addresses_from_idi(self):
        address = [
            {
                'complete': 'address',
                'city': 'city',
                'state': 'state',
                'zip': 12345,
                'meta': {'lastSeen': '20190101'},
            },
        ]
        self.upload_from_idi.get_addresses_from_idi(address)
        self.assertEqual(self.skip_trace_property1.returned_address_1, 'address')
        self.assertEqual(self.skip_trace_property1.returned_city_1, 'city')
        self.assertEqual(self.skip_trace_property1.returned_state_1, 'state')
        self.assertEqual(self.skip_trace_property1.returned_zip_1, 12345)
        self.assertEqual(
            self.skip_trace_property1.returned_address_last_seen_1, datetime(2019, 1, 1).date())

    def test_get_relationship_data_from_idi(self):
        relationship = [
            {
                'name': {
                    'first': 'First',
                    'last': 'Last',
                },
                'phone': [
                    {
                        'number': 8888888888,
                        'type': 'Mobile',
                        'disconnected': False,
                        'providerName': 'Provider',
                        'meta': {'lastSeen': '20190101'},
                    },
                ],
            },
        ]
        self.upload_from_idi.get_relationship_data_from_idi(relationship)
        self.assertEqual(self.skip_trace_property1.relative_1_first_name, 'First')
        self.assertEqual(self.skip_trace_property1.relative_1_last_name, 'Last')
        self.assertEqual(self.skip_trace_property1.relative_1_phone1, '8888888888')

    def test_get_ip_from_idi(self):
        ip = [{'data': '127.0.0.1', 'meta': {'lastSeen': '20190101'}}]
        self.upload_from_idi.get_ip_from_idi(ip)
        self.assertEqual(self.skip_trace_property1.returned_ip_address, '127.0.0.1')
        self.assertEqual(
            self.skip_trace_property1.returned_ip_last_seen, datetime(2019, 1, 1).date())

    def test_get_dates_from_idi(self):
        result = {
            'foreclosure': [{'detail': [{'documentDate': {'sortable': '20190101'}}]}],
            'lien': [{'record': [{'date': {'sortable': '20190102'}}]}],
            'judgment': [{'record': [{'date': {'sortable': '20190103'}}]}],

        }
        self.upload_from_idi.get_date_fields_from_idi(result)
        self.assertEqual(
            self.skip_trace_property1.returned_foreclosure_date, datetime(2019, 1, 1).date())
        self.assertEqual(
            self.skip_trace_property1.returned_lien_date, datetime(2019, 1, 2).date())
        self.assertEqual(
            self.skip_trace_property1.returned_judgment_date, datetime(2019, 1, 3).date())

    def test_skiptrace_run_priority(self):
        """
        Priority should be as follows:
        1) if suppress against database is off always run against IDI
        2) if suppress against database is on check for matches with same company
        3) if suppress agasint database is on check for matches in other companies
        4) if suppress against database is on and no match found, check IDI
        """
        # Create extra skip trace properties
        skip_trace_property3 = mommy.make(
            "sherpa.SkipTraceProperty",
            returned_phone_1=2222222222,
            returned_phone_2=3333333333,
            returned_phone_3=4444444444,
            prop=self.prop,
        )
        skip_trace_property4 = mommy.make(
            "sherpa.SkipTraceProperty",
            returned_phone_1=2222222222,
            returned_phone_2=3333333333,
            returned_phone_3=4444444444,
            prop=self.prop,
        )

        # Create extra prospect
        prospect2 = mommy.make("sherpa.Prospect")

        delivery_line1 = 'abcdefgh'
        zip_code = 12346
        first_name = 'First'
        last_name = 'Last'
        nine_months = django_tz.now() - timedelta(days=90)
        less_nine_months = nine_months + timedelta(days=1)
        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property1.validated_property_zipcode = zip_code
        self.skip_trace_property2.validated_property_status = 'validated'
        upload_skip_trace2 = mommy.make('UploadSkipTrace', company=self.company2)
        self.skip_trace_property2.upload_skip_trace = upload_skip_trace2
        self.skip_trace_property2.has_hit = True
        self.skip_trace_property2.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property2.validated_property_zipcode = zip_code
        self.skip_trace_property2.submitted_owner_first_name = first_name
        self.skip_trace_property2.submitted_owner_last_name = last_name
        self.skip_trace_property2.created = less_nine_months
        skip_trace_property3.validated_property_status = 'validated'
        skip_trace_property3.upload_skip_trace = self.skip_trace
        skip_trace_property3.has_hit = True
        skip_trace_property3.validated_property_delivery_line_1 = delivery_line1
        skip_trace_property3.validated_property_zipcode = zip_code
        skip_trace_property3.submitted_owner_first_name = first_name
        skip_trace_property3.submitted_owner_last_name = last_name
        skip_trace_property4.validated_property_status = 'validated'
        skip_trace_property4.upload_skip_trace = upload_skip_trace2
        skip_trace_property4.has_hit = True
        skip_trace_property4.validated_property_delivery_line_1 = delivery_line1
        skip_trace_property4.validated_property_zipcode = zip_code
        skip_trace_property4.submitted_owner_first_name = first_name
        skip_trace_property4.submitted_owner_last_name = last_name
        skip_trace_property4.created = nine_months

        update_fields = [
            'upload_skip_trace',
            'created',
            'has_hit',
            'validated_property_status',
            'validated_property_delivery_line_1',
            'validated_property_zipcode',
            'submitted_owner_first_name',
            'submitted_owner_last_name',
        ]
        skip_trace_properties = [
            self.skip_trace_property1,
            self.skip_trace_property2,
            skip_trace_property3,
            skip_trace_property4,
        ]
        for obj in skip_trace_properties:
            obj.save(update_fields=update_fields)

        # Turn off 'suppress_against_database' should be IDI run only
        stats = {
            'total_billable_hits': 1,
            'total_hits': 1,
            'total_internal_hits': 0,
            'total_existing_matches': 0,
        }
        self.skip_trace.suppress_against_database = False
        self.skip_trace.save(update_fields=['suppress_against_database'])
        self._run_process_skip_trace_record(stats)

        # Turn on 'suppress_against_database' should find one match same company
        stats['total_existing_matches'] += 1
        stats['total_hits'] += 1
        self.skip_trace.suppress_against_database = True
        self.skip_trace.save(update_fields=['suppress_against_database'])
        self._run_process_skip_trace_record(stats)

        # Change the company on the one matching property. Should have an internal hit
        upload_skip_trace2 = mommy.make('UploadSkipTrace', company=self.company2)
        skip_trace_property3.upload_skip_trace = upload_skip_trace2
        skip_trace_property3.save(update_fields=['upload_skip_trace'])
        stats['total_internal_hits'] += 1
        stats['total_hits'] += 1
        stats['total_billable_hits'] += 1
        self._run_process_skip_trace_record(stats)

        # Find one matching `Prospect` same company
        delivery_line1 = 'abcdefgj'
        zip_code = 12346
        self.prospect.company = self.skip_trace_property1.upload_skip_trace.company
        self.prospect.validated_property_status = 'validated'
        self.prospect.property_address = f"{delivery_line1} {delivery_line1}"
        self.prospect.property_zip = zip_code
        self.prospect.first_name = first_name
        self.prospect.last_name = last_name
        self.prospect.created_date = less_nine_months
        self.prospect.phone_raw = 7777777777
        prospect2.company = self.company2
        prospect2.validated_property_status = 'validated'
        prospect2.property_address = f"{delivery_line1} {delivery_line1}"
        prospect2.property_zip = zip_code
        prospect2.first_name = first_name
        prospect2.last_name = last_name
        prospect2.created_date = nine_months
        prospect2.phone_raw = 7777777777
        self.skip_trace_property1.validated_property_delivery_line_1 = delivery_line1
        self.skip_trace_property1.validated_property_delivery_line_2 = delivery_line1
        self.skip_trace_property1.validated_property_zipcode = zip_code
        skip_trace_update_fields = [
            'validated_property_status',
            'validated_property_delivery_line_1',
            'validated_property_delivery_line_2',
            'validated_property_zipcode',
        ]
        prospect_update_fields = [
            'company',
            'validated_property_status',
            'property_address',
            'property_zip',
            'first_name',
            'last_name',
            'created_date',
            'phone_raw',
        ]
        self.prospect.save(update_fields=prospect_update_fields)
        prospect2.save(update_fields=prospect_update_fields)
        self.skip_trace_property1.save(update_fields=skip_trace_update_fields)

        stats['total_hits'] += 1
        stats['total_existing_matches'] += 1
        self._run_process_skip_trace_record(stats)

    def _run_process_skip_trace_record(self, stats):
        self.process_skip_trace_record.start()
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.total_internal_hits, stats['total_internal_hits'])
        self.assertEqual(self.skip_trace.total_hits, stats['total_hits'])
        self.assertEqual(self.skip_trace.total_existing_matches, stats['total_existing_matches'])
        self.assertEqual(self.skip_trace.total_billable_hits, stats['total_billable_hits'])

    def test_error_email_is_not_sent_by_default(self):
        error_upload_skip_trace = mommy.make(
            'sherpa.UploadSkipTrace',
            status=UploadSkipTrace.Status.ERROR,
        )

        original_count = len(mail.outbox)
        send_skip_trace_error_upload_email_task(error_upload_skip_trace.id)
        self.assertEqual(len(mail.outbox), original_count)

    @override_settings(SKIP_TRACE_SEND_ERROR_EMAIL=True)
    def test_can_send_error_email(self):
        error_upload_skip_trace = mommy.make(
            'sherpa.UploadSkipTrace',
            status=UploadSkipTrace.Status.ERROR,
        )

        original_count = len(mail.outbox)
        send_skip_trace_error_upload_email_task(error_upload_skip_trace.id)
        self.assertEqual(len(mail.outbox), original_count + 1)


@override_settings(task_always_eager=False)
class UploadSkipTraceModelTestCase(SkipTraceDataMixin, BaseTestCase):
    def test_has_alternate_name(self):
        self.assertFalse(self.skip_trace_property1.has_alternate_name)
        self.skip_trace_property1.returned_fullname = 'Alternate Name'
        self.skip_trace_property1.save(update_fields=['returned_fullname'])
        self.assertTrue(self.skip_trace_property1.has_alternate_name)

    def test_is_entity(self):
        self.skip_trace_property1.submitted_owner_first_name = 'Corpus'
        self.skip_trace_property1.save(update_fields=['submitted_owner_first_name'])
        self.assertFalse(self.skip_trace_property1.is_entity)
        self.skip_trace_property1.submitted_owner_first_name = 'Test Corp'
        self.skip_trace_property1.save(update_fields=['submitted_owner_first_name'])
        self.assertTrue(self.skip_trace_property1.is_entity)

    def test_demo_account_skiptrace_eligibility(self):
        self.company1.is_demo = True
        self.company1.save()

        # Demo accounts should be eligible to start with.
        self.assertTrue(self.george_user.profile.can_skiptrace)

        # Create 2x skip traces
        for _ in range(2):
            mommy.make(
                'sherpa.UploadSkipTrace',
                created_by=self.george_user,
                company=self.company1,
                status=UploadSkipTrace.Status.COMPLETE,
            )
        self.assertFalse(self.george_user.profile.can_skiptrace)

        # Check that another user in company can create skip traces.
        self.assertTrue(self.john_user.profile.can_skiptrace)

        # And finally, check that non-demo account is eligible
        self.company1.is_demo = False
        self.company1.save()
        self.assertTrue(self.george_user.profile.can_skiptrace)

    def test_can_create_prospects_from_skip_trace(self):
        # This is testing creating Prospects using UploadSkipTrace. Test for UploadProspect
        # is done separately.
        from sherpa.models import Prospect

        self.skip_trace_property1.submitted_owner_first_name = 'First'
        self.skip_trace_property1.submitted_owner_last_name = 'Last'
        self.skip_trace_property1.validated_property_delivery_line_1 = "Line 1"
        self.skip_trace_property1.validated_property_city_name = "City"
        self.skip_trace_property1.validated_property_state_abbreviation = "TX"
        self.skip_trace_property1.validated_property_zipcode = '12345'
        self.skip_trace_property1.validated_property_status = 'validated'
        self.skip_trace_property1.save(update_fields=[
            'validated_property_delivery_line_1',
            'validated_property_city_name',
            'validated_property_state_abbreviation',
            'validated_property_zipcode',
            'validated_property_status',
            'submitted_owner_first_name',
            'submitted_owner_last_name',
        ])
        Prospect.objects.create_from_skip_trace_property(self.skip_trace_property1)

        self.assertIsNotNone(self.skip_trace_property1.prop)
        for phone in self.skip_trace_property1.phone_list:
            self.assertTrue(Prospect.objects.filter(phone_raw=phone).exists())


@override_settings(task_always_eager=False)
class SkipTraceUploadAPITestCase(SkipTraceDataMixin, BaseAPITestCase):
    list_url = reverse('uploadskiptrace-list')
    map_fields_url = reverse('uploadskiptrace-map-fields')
    single_skip_trace_url = reverse('uploadskiptrace-single')

    def setUp(self):
        super(SkipTraceUploadAPITestCase, self).setUp()
        self.skip_trace.company = self.george_user.profile.company
        self.skip_trace.created_by = self.george_user
        self.skip_trace.status = UploadSkipTrace.Status.COMPLETE
        self.skip_trace.property_address_column_number = 1
        self.skip_trace.save()
        self.skip_trace_property1.upload_skip_trace = self.skip_trace
        self.skip_trace_property1.property_address = '123 Address St'
        self.skip_trace_property1.save()

        # Setup detail urls
        detail_kwargs = {'pk': self.skip_trace.pk}
        self.export_url = reverse('uploadskiptrace-export', kwargs=detail_kwargs)
        self.push_url = reverse('uploadskiptrace-push-to-campaign', kwargs=detail_kwargs)

    def test_anonymous_user_cant_fetch_skip_trace_uploads(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_fetch_skip_trace_uploads(self):
        response = self.george_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(
            response.json().get('results')[0].get('createdBy').get('fullName'),
            self.george_user.get_full_name(),
        )

    def test_user_cant_fetch_other_companies_skip_trace_uploads(self):
        response = self.thomas_client.get(self.list_url)
        # thomas' company has no skip traces. company1 has at least one,
        # but verify that thomas can't see it.
        self.assertTrue(self.company2.uploadskiptrace_set.count() == 0)
        self.assertTrue(self.company1.uploadskiptrace_set.count() > 0)
        self.assertEqual(response.json()['count'], 0)

    def test_fetch_skip_trace_uploads_excludes_status_of_setup(self):
        self.skip_trace.status = UploadSkipTrace.Status.SETUP
        self.skip_trace.save()
        response = self.george_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)
        self.assertTrue(self.company1.uploadskiptrace_set.count() > 0)

    def test_can_filter_by_status_running(self):
        url = self.list_url + '?status=running'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)
        self.skip_trace.status = UploadSkipTrace.Status.RUNNING
        self.skip_trace.save()
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

    def test_can_filter_by_push_to_campaign_status_open(self):
        url = self.list_url + '?push_to_campaign_status=open'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.skip_trace.push_to_campaign_status = 'running'
        self.skip_trace.save()
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)

    def test_can_filter_by_is_archived_false(self):
        url = self.list_url + '?is_archived=false'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)
        self.skip_trace.is_archived = True
        self.skip_trace.save()
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)

    def test_can_filter_by_is_archived_true(self):
        url = self.list_url + '?is_archived=true'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)
        self.skip_trace.is_archived = True
        self.skip_trace.save()
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

    def test_can_filter_by_created_by(self):
        url = f'{self.list_url}?created_by__id=7'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)

        # Filter by george's id.
        url = f'{self.list_url}?created_by__id={self.george_user.id}'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['count'] > 0)
        for data in response.json().get('results'):
            self.assertEqual(data.get('createdBy').get('id'), self.george_user.id)

    def test_cant_run_single_skip_trace_without_authentication(self):
        response = self.client.get(self.single_skip_trace_url, {})
        self.assertEqual(response.status_code, 401)

    def test_must_have_credits_to_run_single_skip_trace(self):
        data = {
            'propertyOnly': True,
            'propertyAddress': '123 Address St',
            'propertyCity': 'City',
            'propertyState': 'State',
            'propertyZip': 12345,
        }
        self.george_user.profile.company.sherpa_balance = 0
        self.george_user.profile.company.save(update_fields=['sherpa_balance'])
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["detail"],
                         "You don't have enough Sherpa Credits to run a Single Skip Trace.")

    def test_must_send_valid_data_to_run_single_skip_trace(self):
        self.george_user.profile.company.sherpa_balance = 40
        self.george_user.profile.company.save(update_fields=['sherpa_balance'])
        data = dict()
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'Must include property only')
        data['propertyOnly'] = False
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'Must include name')
        data['lastName'] = 'Name'
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'Must include all address fields')
        data['propertyAddress'] = '123 Address St'
        data['propertyCity'] = 'City'
        data['propertyState'] = "State"
        data['propertyZip'] = 12345
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'Must include all address fields')
        data['mailingAddress'] = '123 Address St'
        data['mailingCity'] = 'City'
        data['mailingState'] = "State"
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'Must include all address fields')

    def test_can_run_single_skip_trace_property_only(self):
        data = {
            'propertyOnly': True,
            'propertyAddress': '123 Address St',
            'propertyCity': 'City',
            'propertyState': 'State',
            'propertyZip': 12345,
        }
        self.george_user.profile.company.sherpa_balance = 40
        self.george_user.profile.company.save(update_fields=['sherpa_balance'])
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 201)
        skip_trace_id = response.json().get('id', None)
        self.assertIsNotNone(skip_trace_id)
        skip_trace = UploadSkipTrace.objects.get(id=skip_trace_id)
        skip_trace_property = SkipTraceProperty.objects.get(upload_skip_trace=skip_trace)
        self.assertEqual(skip_trace_property.submitted_property_address, '123 Address St')
        self.assertEqual(skip_trace_property.submitted_property_city, 'City')
        self.assertEqual(skip_trace_property.submitted_property_state, 'State')
        self.assertEqual(skip_trace_property.submitted_property_zip, '12345')
        self.assertTrue(skip_trace_property.upload_skip_trace.is_single_upload)

    def test_can_run_single_skip_trace(self):
        data = {
            'propertyOnly': False,
            'propertyAddress': 'Property St',
            'propertyCity': 'Property City',
            'propertyState': 'Property State',
            'propertyZip': 12345,
            'firstName': 'First',
            'lastName': 'Last',
            'mailingAddress': 'Mailing St',
            'mailingCity': 'Mail City',
            'mailingState': 'Mail State',
            'mailingZip': 12346,
        }
        self.george_user.profile.company.sherpa_balance = 40
        self.george_user.profile.company.save(update_fields=['sherpa_balance'])
        response = self.george_client.post(self.single_skip_trace_url, data)
        self.assertEqual(response.status_code, 201)
        skip_trace_id = response.json().get('id', None)
        self.assertIsNotNone(skip_trace_id)
        skip_trace = UploadSkipTrace.objects.get(id=skip_trace_id)
        skip_trace_property = SkipTraceProperty.objects.get(upload_skip_trace=skip_trace)
        self.assertEqual(skip_trace_property.submitted_property_address, 'Property St')
        self.assertEqual(skip_trace_property.submitted_property_city, 'Property City')
        self.assertEqual(skip_trace_property.submitted_property_state, 'Property State')
        self.assertEqual(skip_trace_property.submitted_property_zip, '12345')
        self.assertEqual(skip_trace_property.submitted_mailing_address, 'Mailing St')
        self.assertEqual(skip_trace_property.submitted_mailing_city, 'Mail City')
        self.assertEqual(skip_trace_property.submitted_mailing_state, 'Mail State')
        self.assertEqual(skip_trace_property.submitted_mailing_zip, '12346')
        self.assertEqual(skip_trace_property.submitted_owner_first_name, 'First')
        self.assertEqual(skip_trace_property.submitted_owner_last_name, 'Last')
        self.assertTrue(skip_trace_property.upload_skip_trace.is_single_upload)

    def test_cant_map_fields_without_authentication(self):
        response = self.client.get(self.map_fields_url, {})
        self.assertEqual(response.status_code, 401)

    def test_must_send_valid_data_to_map_fields(self):
        response = self.george_client.post(self.map_fields_url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['detail'],
            'Must send `headers_matched`, `valid_data` and `uploaded_filename` in request.',
        )

    def test_can_map_fields(self):
        headers_matched = [
            {'letter': 'A', 'matched_key': 'property_street'},
            {'letter': 'B', 'matched_key': 'property_city'},
            {'letter': 'C', 'matched_key': 'property_state'},
            {'letter': 'D', 'matched_key': 'property_zipcode'},
            {'letter': 'E', 'matched_key': 'custom_1'},
            {'letter': 'F', 'matched_key': 'custom_2'},
            {'letter': 'G', 'matched_key': 'custom_3'},
            {'letter': 'H', 'matched_key': 'custom_4'},
            {'letter': 'I', 'matched_key': 'custom_5'},
            {'letter': 'J', 'matched_key': 'custom_6'},
        ]
        valid_data = [
            {
                'property_street': '123 Address Lane',
                'property_city': 'Testville',
                'property_state': 'TX',
                'property_zipcode': '79423',
                'custom_1': 'c1',
                'custom_2': 'c2',
                'custom3': 'c3',
                'custom_4': 'c4',
                'custom_5': 'c5',
                'custom_6': 'c6',
            },
            {
                'property_street': '123 Address Lane',
                'property_city': 'Testville',
                'property_state': 'TX',
                'property_zipcode': '79423',
                'custom_1': 'c1',
                'custom_2': 'c2',
                'custom3': 'c3',
                'custom_4': 'c4',
                'custom_5': 'c5',
                'custom_6': 'c6',
            },
        ]
        data = {
            'valid_data': json.dumps(valid_data),
            'headers_matched': json.dumps(headers_matched),
            'uploaded_filename': 'test.csv',
        }
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 201)
        skip_trace = UploadSkipTrace.objects.get(id=response.json()['id'])
        self.assertIsNotNone(skip_trace)
        self.assertEqual(skip_trace.uploaded_filename, 'test.csv')
        self.assertEqual(skip_trace.total_rows, 2)
        self.assertEqual(skip_trace.created_by, self.george_user)
        for i, h in enumerate([header['matched_key'] for header in headers_matched]):
            self.assertEqual(getattr(skip_trace, f'{h}_column_number'), i)

        # test that tags uploaded are stored on the UploadSkipTrace instance
        data["property_tag_ids"] = ['bad_id']
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['propertyTagIds']['0'][0], 'A valid integer is required.')

        # not in company
        data["property_tag_ids"] = [99999]
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 400)
        self.assertTrue("do not exist" in response.json()['detail'])

        # test good tag
        property_tag = self.george_user.profile.company.propertytag_set.first()
        data["property_tag_ids"] = [property_tag.pk]
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 201)
        skip_trace = UploadSkipTrace.objects.get(id=response.json()['id'])
        self.assertIsNotNone(skip_trace)
        self.assertEqual(skip_trace.property_tags.count(), 1)

    def test_can_get_specific_skip_trace(self):
        url = self.list_url + str(self.skip_trace.id) + '/'
        response = self.george_client.get(url)
        self.assertIsNotNone(response.json().get('estimateRange', None))

    def test_can_purchase_skip_trace_defaults_suppress_against_database_true(self):
        url = self.list_url + str(self.skip_trace.id) + '/purchase/'
        self.skip_trace.status = UploadSkipTrace.Status.SETUP
        self.skip_trace.save(update_fields=['status'])
        response = self.george_client.patch(url)
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.status, UploadSkipTrace.Status.SENT_TO_TASK)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.skip_trace.suppress_against_database)

    def test_can_purchase_skip_trace_suppress_against_database_false(self):
        data = {'suppress_against_database': False}
        url = self.list_url + str(self.skip_trace.id) + '/purchase/'
        self.skip_trace.status = UploadSkipTrace.Status.SETUP
        self.skip_trace.save(update_fields=['status'])
        response = self.george_client.patch(url, data)
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.status, UploadSkipTrace.Status.SENT_TO_TASK)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.skip_trace.suppress_against_database)

    def test_user_can_export_skip_trace_csv(self):
        # Verify that a csv response is returned.
        response = self.george_client.get(self.export_url)
        self.assertEqual(response.status_code, 200)
        download_id = response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = SkipTraceProperty.objects.filter(
            upload_skip_trace_id=download.filters['upload_skip_trace_id'],
        )
        resource = SkipTraceResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        csv_count = len([data for data in csv_data])

        # Verify some minimal data in the csv.
        self.assertEqual(csv_count, 1)
        for data in csv_data:
            self.assertEqual(
                data.get('Property Address'),
                self.skip_trace_property1.submitted_property_address,
            )
            break

    def test_user_cant_export_other_users_skip_trace_csv(self):
        response = self.thomas_client.get(self.export_url)
        self.assertEqual(response.status_code, 404)

    def test_push_to_campaign(self):
        url = self.push_url
        payload = {}

        # Validate serializer data.
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('campaign')[0], 'This field is required.')
        self.assertEqual(response.json().get('importType')[0], 'This field is required.')

        # Check for invalid import type
        payload = {"campaign": 999999, "importType": "invalid"}
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('importType'), None)

        # Check for invalid campaign
        payload["importType"] = "all"
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('campaign'), None)

        # Verify that the push can be started
        payload["campaign"] = self.campaign.id
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        # Confirm relevant data has been updated.
        self.skip_trace.refresh_from_db()
        self.assertEqual(self.skip_trace.push_to_campaign_import_type, "all")
        self.assertEqual(self.skip_trace.push_to_campaign_status,
                         UploadSkipTrace.PushToCampaignStatus.QUEUED)
