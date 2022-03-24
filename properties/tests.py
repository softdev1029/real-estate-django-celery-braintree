from datetime import date

from model_mommy import mommy

from django.urls import reverse

from sherpa.tests import CompanyOneMixin, CompanyTwoMixin, NoDataBaseTestCase
from .models import PropertyTag
from .utils import get_or_create_address, get_or_create_attom_tags


class PropertyTagAPITestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    list_url = reverse('propertytag-list')

    def setUp(self):
        self.company1_tag1 = mommy.make('properties.PropertyTag', company=self.company1)
        self.company1_tag2 = mommy.make('properties.PropertyTag', company=self.company1)
        self.company2_tag1 = mommy.make('properties.PropertyTag', company=self.company2)
        self.detail_url = reverse('propertytag-detail', kwargs={'pk': self.company1_tag1.pk})

    def test_can_get_property_tag_list(self):
        response = self.master_admin_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), self.company1.propertytag_set.count())

    def test_can_create_new_property_tag(self):
        payload = {'name': 'A New Tag', 'distressIndicator': False}
        response = self.master_admin_client.post(self.list_url, payload)
        self.assertEqual(response.status_code, 201)
        tag = PropertyTag.objects.get(id=response.json().get('id'))
        self.assertEqual(tag.company, self.company1)

    def test_can_update_property_tag(self):
        updated_name = 'updated'
        payload = {'name': updated_name}
        response = self.master_admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.json().get('name'), updated_name)


class PropertyTagModelTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def test_new_property_tag_has_correct_order(self):
        tags = ['dog', 'cat', 'squirrel']
        current_order = self.company1.propertytag_set.last().order
        for tag in tags:
            new = mommy.make('properties.PropertyTag', company=self.company1, name=tag)
            self.assertEqual(new.order, current_order + 1)
            current_order = new.order


class PropertiesUtilTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self, quitclaim_null=False):
        self.attom_assessor = mommy.make('properties.AttomAssessor')
        self.address = mommy.make('properties.Address', attom=self.attom_assessor)
        mommy.make('properties.AttomPreForeclosure',
                   attom_id=self.attom_assessor,
                   foreclosure_recording_date=date(2021, 5, 19))
        if quitclaim_null:
            mommy.make('properties.AttomRecorder', attom_id=self.attom_assessor, quitclaim_flag=0)
        else:
            mommy.make('properties.AttomRecorder', attom_id=self.attom_assessor, quitclaim_flag=1)

    def test_get_or_create_address(self):
        valid_data = {
            'street': '123 Fake st.',
            'city': 'Faketown',
            'state': 'AA',
            'zip': '12345',
        }

        # Test required fields:
        invalid_data = valid_data
        invalid_data['street'] = None
        self.assertEqual(None, get_or_create_address(invalid_data))

        # Test long field names:
        too_long = 'a' * 150
        long_data = {
            'street': too_long,
            'city': too_long,
            'state': too_long,
            'zip': too_long,
        }
        self.assertNotEqual(None, get_or_create_address(long_data))

    def test_get_or_create_attom_tags(self):
        created_attom_tags = get_or_create_attom_tags(self.address, self.company1)
        tags_name = PropertyTag.objects.filter(id__in=created_attom_tags). \
            values_list('name', flat=True)
        self.assertEqual(set(tags_name), set(['Quitclaim', 'Pre-foreclosure']))

        # If quitclaim_flag column is zero or none fuc wont create tag.
        self.setUp(True)
        created_attom_tags = get_or_create_attom_tags(self.address, self.company1)
        tags_name = PropertyTag.objects.filter(id__in=created_attom_tags). \
            values_list('name', flat=True)
        self.assertEqual(set(tags_name), set(['Pre-foreclosure']))
