import csv
import json
import os

from django.core.files.base import ContentFile
from django.test.testcases import TestCase
from django.urls import reverse

from campaigns.tests import CampaignDataMixin
from core.utils import clean_phone
from sherpa.models import LitigatorList, UploadLitigatorCheck, UploadLitigatorList
from sherpa.tests import BaseTestCase, CompanyOneMixin
from ..tasks import upload_litigator_list_task


class LitigationChecksUploadTestCase(CampaignDataMixin, BaseTestCase):
    def test_upload_via_flatfile(self):
        headers_matched = [
            {'letter': 'A', 'matched_key': 'street'},
            {'letter': 'B', 'matched_key': 'city'},
            {'letter': 'C', 'matched_key': 'state'},
            {'letter': 'D', 'matched_key': 'zipcode'},
            {'letter': 'E', 'matched_key': 'phone_1_number'},
        ]
        valid_data = [
            {
                'street': '123 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555555,
            },
            {
                'street': '123 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555556,
            },
        ]
        self.client.force_login(self.george_user)
        payload =  \
            {
                'valid_data': json.dumps(valid_data),
                'headers_matched': json.dumps(headers_matched),
                'uploaded_filename': 'test.csv',
                'campaign_id': self.george_campaign.id,
            }
        response = self.client.post(
            reverse('litigator_check_map_fields'),
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode('utf8'))

        upload_litigator_check = UploadLitigatorCheck.objects.get(token=data.get('id'))

        self.assertEqual(upload_litigator_check.uploaded_filename, 'test.csv')
        self.assertEqual(upload_litigator_check.total_rows, 2)
        for i, h in enumerate([header['matched_key'] for header in headers_matched]):
            if h != 'phone_1_number':
                self.assertEqual(getattr(upload_litigator_check, f'{h}_column_number'), i)
            else:
                self.assertEqual(getattr(upload_litigator_check, 'phone_1_number'), i)


class LitigationUploadTestCase(CompanyOneMixin, TestCase):
    def test_litigator_upload(self):
        with open(
            os.path.join(os.path.dirname(__file__), 'files/litigator_upload_test_file.csv'),
            'r',
        ) as f:
            u = UploadLitigatorList.objects.create(
                company_id=self.company1.id,
                file=ContentFile(f.read().encode('utf-8'), name='file.csv'),
            )
            f.seek(0)
            reader = csv.reader(f)
            numbers = [clean_phone(number) for number in reader]
        upload_litigator_list_task(u.id)

        u.refresh_from_db()

        self.assertEqual(u.status, UploadLitigatorList.Status.COMPLETE)
        self.assertEqual(u.total_rows, 5)

        for number in numbers:
            self.assertTrue(LitigatorList.objects.filter(phone=number).exists())
