from model_mommy import mommy

from django.urls import reverse

from sherpa.models import AreaCodeState, Market
from sherpa.tests import BaseTestCase, CompanyOneMixin, CompanyTwoMixin, NoDataBaseTestCase
from .utils import format_telnyx_available_numbers


class MarketDataMixin:
    def setUp(self):
        super(MarketDataMixin, self).setUp()
        self.parent_market1 = mommy.make('sherpa.AreaCodeState', city='Fakeville', state='WA')
        self.parent_market2 = mommy.make('sherpa.AreaCodeState', city='Imaginary', state='CO')
        self.parent_market3 = mommy.make('sherpa.AreaCodeState', city='Imaginary', state='TX')

        self.market1 = mommy.make(
            'sherpa.Market',
            company=self.company1,
            parent_market=self.parent_market1,
        )
        self.market2 = mommy.make(
            'sherpa.Market',
            company=self.company1,
            parent_market=self.parent_market2,
        )
        self.market3 = mommy.make(
            'sherpa.Market',
            company=self.company2,
            parent_market=self.parent_market1,
        )

        self.phone_number_1 = mommy.make(
            'sherpa.PhoneNumber',
            company=self.company1,
            market=self.market1,
            phone='5091111111',
        )
        self.phone_number_2 = mommy.make(
            'sherpa.PhoneNumber',
            company=self.company1,
            market=self.market1,
            phone='5092222222',
        )


class MarketModelTestCase(MarketDataMixin, BaseTestCase):

    def test_can_deactivate_market(self):
        # TODO: can't do anything until verifying twilio test credentials.
        pass

    def test_campaign_count_shows_only_active(self):
        mommy.make('sherpa.Campaign', market=self.market1)
        mommy.make('sherpa.Campaign', market=self.market1, is_archived=True)
        active_count = self.market1.campaign_set.filter(is_archived=False).count()
        self.assertEqual(self.market1.active_campaigns.count(), active_count)


class MarketAPITestCase(MarketDataMixin, CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):
    list_url = reverse('market-list')
    purchase_url = reverse('market-purchase')
    availability_url = reverse('market-check-availability')

    def setUp(self):
        super(MarketAPITestCase, self).setUp()
        self.detail_url = reverse('market-detail', kwargs={'pk': self.market1.id})

    def test_can_get_markets(self):
        response = self.master_admin_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)

        results = response.json().get('results')
        self.assertEqual(len(results), self.company1.market_set.count())

        for market_data in results:
            self.assertEqual(market_data.get('company'), self.company1.id)

    def test_can_get_single_market(self):
        response = self.master_admin_client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)

    def test_campaign_count_returns_only_active(self):
        mommy.make('sherpa.Campaign', market=self.market1)
        mommy.make('sherpa.Campaign', market=self.market1, is_archived=True)

        response = self.master_admin_client.get(self.list_url)

        for market_data in response.json().get('results'):
            market = Market.objects.get(id=market_data.get('id'))
            expected = market.campaign_set.filter(is_archived=False).count()
            self.assertEqual(market_data.get('campaignCount'), expected)

    def test_cant_update_others_market(self):
        new_name = 'New Name'
        payload = {'name': new_name}
        response = self.company2_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_can_filter_by_active(self):
        # Prep the data for the test case.
        self.market1.is_active = False
        self.market1.save()
        active_filter_url = self.list_url + '?is_active=true'
        inactive_filter_url = self.list_url + '?is_active=false'

        # Check that we can get only active records.
        active_response = self.master_admin_client.get(active_filter_url)
        active_results = active_response.json().get('results')
        self.assertTrue(len(active_results) > 0)
        for result in active_results:
            self.assertTrue(result.get('isActive'))

        # Check that we can get only inactive records.
        inactive_response = self.master_admin_client.get(inactive_filter_url)
        inactive_results = inactive_response.json().get('results')
        self.assertTrue(len(inactive_results) > 0)
        for result in inactive_results:
            self.assertFalse(result.get('isActive'))

    def test_can_update_market_call_forwarding_number(self):
        # Test invalid call forwarding
        invalid_number = 'EHDDLS'
        payload = {'callForwardingNumber': invalid_number}
        response = self.master_admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get('callForwardingNumber')[0],
            'Call forwarding number should be 10 digits.',
        )

        new_call_forwarding = '4257779999'
        payload = {'callForwardingNumber': new_call_forwarding}
        response = self.master_admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('callForwardingNumber'), new_call_forwarding)

    def test_can_purchase_market(self):
        response = self.master_admin_client.post(self.purchase_url)
        self.assertEqual(response.status_code, 400)
        payload = {
            'areaCode': 806,
            'marketName': 'Test',
            'callForwardingNumber': 5555555,
            'masterAreaCodeStateId': self.parent_market1.id,
        }
        response = self.master_admin_client.post(self.purchase_url, payload)
        self.assertEqual(response.status_code, 200)

    def test_purchase_existing_inactive_market(self):
        # Should reactivate the inactive market
        market = self.market1
        market.is_active = False
        market.save()
        initial_count = self.company1.market_set.count()

        response = self.master_admin_client.post(self.purchase_url)
        self.assertEqual(response.status_code, 400)
        payload = {
            'areaCode': 206,
            'marketName': 'Purchase existing...',
            'callForwardingNumber': 5555555555,
            'masterAreaCodeStateId': market.parent_market.id,
        }
        response = self.master_admin_client.post(self.purchase_url, payload)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.company1.market_set.count(), initial_count)
        market.refresh_from_db()
        self.assertTrue(market.is_active)

    def test_can_check_market_availability(self):
        response = self.master_admin_client.get(self.availability_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get('detail'),
            'Must include query parameter `area_code_state_id`',
        )

        url = self.availability_url + f"?area_code_state_id={self.parent_market1.id}"
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get('detail'),
            f'Company is already in the parent {self.market1.name} market.',
        )

        url = self.availability_url + f"?area_code_state_id={self.parent_market3.id}"
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'areaCodes': {'Non': 30}, 'quantity': 30})

    def test_inactive_market_is_available(self):
        self.market1.is_active = False
        self.market1.save()

        url = self.availability_url + f"?area_code_state_id={self.parent_market1.id}"
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_can_check_market_number_availability(self):
        url = reverse('market-check-number-availability', kwargs={'pk': self.market1.id})
        # Verify can't check other's market
        valid_payload = {'quantity': 1}
        response = self.company2_client.get(url, valid_payload)
        self.assertEqual(response.status_code, 404)

        # Verify the type validation of quantity.
        str_payload = {'quantity': 'hello'}
        response = self.master_admin_client.get(url, str_payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('must be a valid integer', response.json().get('detail'))

        # Verify that quantity needs to be positive.
        neg_payload = {'quantity': -1}
        response = self.master_admin_client.get(url, neg_payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('must be a valid integer', response.json().get('detail'))

        # To verify the successful response, it can depend on the telnyx api response.
        response = self.master_admin_client.get(url, valid_payload)
        if response.status_code != 200:
            self.assertEqual(response.status_code, 400)
            detail = response.json().get('detail')
            self.assertIn('numbers are available', detail)
        else:
            self.assertEqual(response.json(), {'areaCodes': {'Non': 1}, 'quantity': 1})

    def test_can_purchase_market_numbers(self):
        url = reverse('market-purchase-numbers', kwargs={'pk': self.market1.id})

        # Verify can't check other's market
        valid_payload = {'quantity': 1}
        response = self.company2_client.post(url, valid_payload)
        self.assertEqual(response.status_code, 404)

        # Verify the type validation of quantity.
        str_payload = {'quantity': 'hello'}
        response = self.master_admin_client.post(url, str_payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('quantity')[0], 'A valid integer is required.')

        # Verify that quantity needs to be positive.
        neg_payload = {'quantity': -1}
        response = self.master_admin_client.post(url, neg_payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('quantity')[0],
                         'Ensure this value is greater than or equal to 0.')

        # To verify the successful response, it can depend on the telnyx api response.
        response = self.master_admin_client.post(url, valid_payload)
        if response.status_code != 200:
            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.json().get('detail'), None)

    def test_cant_purchase_numbers_for_inactive_market(self):
        self.market1.is_active = False
        self.market1.save()
        url = reverse('market-purchase-numbers', kwargs={'pk': self.market1.id})
        response = self.master_admin_client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('detail'), None)

    def test_create_and_update_twilio_market(self):
        phone1 = mommy.make('sherpa.PhoneNumber', company=self.company1)
        phone2 = mommy.make('sherpa.PhoneNumber', company=self.company1)
        phone3 = mommy.make('sherpa.PhoneNumber', company=self.company1)

        url = reverse('market-telephony-market')
        payload = {
            'name': 'Twilio Test',
            'call_forwarding': 9999999999,
            'numbers': [phone1.pk, phone2.pk],
            'provider_id': 0,
        }
        response = self.master_admin_client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('name'), payload['name'])
        phone1.refresh_from_db()
        phone2.refresh_from_db()
        self.assertEqual(phone1.market.name, payload['name'])
        self.assertEqual(phone2.market.name, payload['name'])
        self.assertEqual(phone1.provider, 'twilio')
        payload['numbers'] = [phone3.pk]
        response = self.master_admin_client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('name'), payload['name'])
        phone3.refresh_from_db()
        self.assertEqual(phone3.market.name, payload['name'])


class ParentMarketAPITestCase(CompanyOneMixin, NoDataBaseTestCase):
    parent_market_list_url = reverse('areacodestate-list')

    def test_can_get_parent_market_list(self):
        url = self.parent_market_list_url
        expected_count = AreaCodeState.objects.filter(parent_market=True).count()

        # Check that it requires authentication.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

        # Verify that it returns the data.
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), expected_count)


class MarketUtilTestCase(NoDataBaseTestCase):
    def test_format_telnyx_available_number_response(self):
        """
        Test formatting telnyx response.

        Response data copied from:
        https://developers.telnyx.com/docs/api/v2/numbers/Number-Search#listAvailablePhoneNumbers

        Note: The `meta` key is `metadata` in the actual returned response from Telnyx.
        """
        telnyx_response = {
            "data": [
                {
                    "best_effort": False,
                    "cost_information": {
                        "currency": "USD",
                        "monthly_cost": "6.54",
                        "upfront_cost": "3.21",
                    },
                    "phone_number": "+19705555098",
                    "quickship": True,
                    "record_type": "available_phone_number",
                    "region_information": [
                        {
                            "region_name": "US",
                            "region_type": "country_code",
                        },
                    ],
                    "regulatory_requirements": [
                        {
                            "description": "Requirement for providing Proof of Address",
                            "field_type": "address",
                            "label": "Proof of Address",
                            "requirement_type": "end user proof of address",
                        },
                    ],
                    "reservable": True,
                    "vanity_format": "",
                },
            ],
            "metadata": {
                "best_effort_results": 50,
                "total_results": 100,
            },
        }

        formatted = format_telnyx_available_numbers(telnyx_response, return_numbers=True)
        self.assertEqual(
            {
                "phone_numbers": ["9705555098"],
                "area_codes": {
                    "970": 1,
                },
                "quantity": 100,
            },
            formatted,
        )
