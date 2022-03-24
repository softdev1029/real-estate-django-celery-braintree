from datetime import timedelta

from model_mommy import mommy

from django.core import mail
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone as django_tz

from core.utils import clean_phone
from markets.tests import MarketDataMixin
from phone.models.provider import Provider
from sherpa.models import PhoneNumber
from sherpa.tests import BaseAPITestCase, CompanyOneMixin, NoDataBaseTestCase
from sms.models import SMSResult
from . import tasks


class PhoneNumberAPITestCase(MarketDataMixin, BaseAPITestCase):
    phone_number_list_url = reverse('phonenumber-list')
    provider_list_url = reverse('phoneprovider-list')

    def setUp(self):
        super(PhoneNumberAPITestCase, self).setUp()
        self.phone_number1 = mommy.make(
            'sherpa.PhoneNumber',
            market=self.market1,
            phone='2068887777',
            status=PhoneNumber.Status.ACTIVE,
        )
        self.phone_number2 = mommy.make(
            'sherpa.PhoneNumber',
            market=self.market1,
            phone='2068887777',
        )
        self.phone_number3 = mommy.make(
            'sherpa.PhoneNumber',
            market=self.market2,
            phone='2068887777',
        )
        self.phone_number4 = mommy.make(
            'sherpa.PhoneNumber',
            market=self.market3,
            phone='2068887777',
        )

        detail_kwargs = {'pk': self.phone_number1.id}
        self.release_action_url = reverse('phonenumber-release', kwargs=detail_kwargs)
        self.phone_number_detail_url = reverse('phonenumber-detail', kwargs=detail_kwargs)
        self.provider_detail_url = reverse('phoneprovider-detail', kwargs={'pk': Provider.TELNYX})

    def test_anon_cant_get_phone_numbers(self):
        response = self.client.get(self.phone_number_list_url)
        self.assertEqual(response.status_code, 401)

    def test_can_get_phone_numbers(self):
        response = self.george_client.get(self.phone_number_list_url)
        self.assertEqual(response.status_code, 200)

        # Verify that the results are limited to the company.
        response_data = response.json()
        expected_count = PhoneNumber.objects.filter(market__company=self.company1).count()
        self.assertNotEqual(len(response_data), PhoneNumber.objects.count())
        self.assertEqual(len(response_data), expected_count)

    def test_cant_release_others_number(self):
        response = self.thomas_client.post(self.release_action_url)
        self.assertEqual(response.status_code, 404)

    def test_can_release_phone_number(self):
        response = self.george_client.post(self.release_action_url)
        self.assertEqual(response.status_code, 200)

        # Verify that the phone number was updated.
        self.phone_number1.refresh_from_db()
        self.assertEqual(self.phone_number1.status, PhoneNumber.Status.RELEASED)

    def test_can_update_phone_number_status(self):
        active = PhoneNumber.Status.ACTIVE
        inactive = PhoneNumber.Status.INACTIVE

        # Verify that we can toggle the status.
        self.assertEqual(self.phone_number1.status, active)
        payload = {'status': 'inactive'}
        response = self.george_client.patch(self.phone_number_detail_url, payload)
        self.assertEqual(response.json().get('status'), inactive)

        payload = {'status': 'active'}
        response = self.george_client.patch(self.phone_number_detail_url, payload)
        self.assertEqual(response.json().get('status'), active)

        # Verify that we can't toggle status of other company numbers
        payload = {'status': 'active'}
        response = self.thomas_client.patch(self.phone_number_detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_bulk_action_release(self):
        url = reverse('phonenumber-bulk-release')
        response = self.george_client.post(
            url,
            {"values": [self.phone_number1.id]},
        )
        self.phone_number1.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.phone_number1.status, PhoneNumber.Status.RELEASED)

    def test_bulk_action_deactivate(self):
        url = reverse('phonenumber-bulk-deactivate')
        response = self.george_client.post(
            url,
            {"values": [self.phone_number1.id]},
        )
        self.phone_number1.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.phone_number1.status, PhoneNumber.Status.INACTIVE)

    def test_cooldown(self):
        self.market1.current_spam_cooldown_period_end = django_tz.now() + timedelta(hours=2)
        self.market1.save(update_fields=['current_spam_cooldown_period_end'])
        self.market2.current_spam_cooldown_period_end = django_tz.now() + timedelta(hours=2)
        self.market2.save(update_fields=['current_spam_cooldown_period_end'])
        self.market3.current_spam_cooldown_period_end = django_tz.now() + timedelta(hours=2)
        self.market3.save(update_fields=['current_spam_cooldown_period_end'])
        response = self.george_client.get(self.phone_number_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['status'], 'cooldown')

        self.market1.current_spam_cooldown_period_end = django_tz.now() - timedelta(hours=2)
        self.market1.save(update_fields=['current_spam_cooldown_period_end'])
        self.market2.current_spam_cooldown_period_end = django_tz.now() - timedelta(hours=2)
        self.market2.save(update_fields=['current_spam_cooldown_period_end'])
        self.market3.current_spam_cooldown_period_end = django_tz.now() - timedelta(hours=2)
        self.market3.save(update_fields=['current_spam_cooldown_period_end'])
        response = self.george_client.get(self.phone_number_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['status'], 'active')

    def test_can_get_provider_data(self):
        response = self.george_client.get(self.provider_detail_url)
        self.assertEqual(response.status_code, 200)


class PhoneNumberTaskTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self):
        super(PhoneNumberTaskTestCase, self).setUp()
        self.market = mommy.make('sherpa.Market', company=self.company1)
        self.sherpa_phone = mommy.make(
            'sherpa.PhoneNumber',
            market=self.market,
            status=PhoneNumber.Status.ACTIVE,
        )

    def test_purchase_phone_numbers(self):
        # Get original data.
        original_count = self.market.phone_numbers.count()
        add_quantity = 5

        # Purchase the numbers.
        user = self.master_admin_user
        tasks.purchase_phone_numbers_task(self.market.id, add_quantity, 2, user.id)

        # Verify the follow-up data is correct.
        self.assertTrue(self.market.phone_numbers.count() == original_count + add_quantity)
        self.assertEqual(len(mail.outbox), 1)

        # Verify the contents of the email.
        email = mail.outbox[0]
        content = email.alternatives[0][0]
        self.assertEqual(email.subject, f'{add_quantity} Sherpa Phone Numbers Added')
        msg = f'{add_quantity} Sherpa phone numbers have been added to your {self.market.name}'
        verify_in = [msg, self.market.name, self.market.company.name]
        for check in verify_in:
            assert check in content

    def test_deactivate_company_markets(self):
        tasks.deactivate_company_markets(self.company1.id)
        self.market.refresh_from_db()
        self.assertFalse(self.market.is_active)
        self.sherpa_phone.refresh_from_db()
        self.assertEqual(self.sherpa_phone.status, PhoneNumber.Status.RELEASED)

    def test_release_inactive_phone_numbers(self):
        ago = django_tz.now() - timedelta(days=8)
        self.sherpa_phone.status = PhoneNumber.Status.INACTIVE
        self.sherpa_phone.last_send_utc = ago
        self.sherpa_phone.save()

        tasks.release_inactive_phone_numbers()
        self.sherpa_phone.refresh_from_db()
        self.assertEqual(self.sherpa_phone.status, PhoneNumber.Status.RELEASED)

    def test_release_company_phone_numbers(self):
        phone_number_list = self.company1.phone_numbers.all()
        tasks.release_company_phone_numbers(phone_number_list, self.company1.id)
        self.sherpa_phone.refresh_from_db()
        self.assertEqual(self.sherpa_phone.status, PhoneNumber.Status.ACTIVE)

    def test_update_sherpa_delivery_rate(self):
        self.assertEqual(self.sherpa_phone.sherpa_delivery_percentage, None)

        # Now we can fake some delivery and update the delivery rate.
        fake_campaign = mommy.make('sherpa.Campaign', company=self.company1)
        fake_message = mommy.make(
            'sherpa.SMSMessage',
            from_number=self.sherpa_phone.full_number,
            campaign=fake_campaign,
        )
        mommy.make('sms.SMSResult', sms=fake_message, status=SMSResult.Status.DELIVERED)
        tasks.update_sherpa_delivery_rate()
        self.sherpa_phone.refresh_from_db()
        self.assertEqual(self.sherpa_phone.sherpa_delivery_percentage * 100, 100)


class PhoneUtilsTestCase(SimpleTestCase):
    def test_clean_phone(self):
        """
        Util function actually in core
        """
        phones_to_clean = {
            "2345678901": "2345678901",
            2345678901.0: "2345678901",
            "+12234567890": "2234567890",
            "1-223-456-7890": "2234567890",
            12234567890: "2234567890",
            "+1(323) 456 7890": "3234567890",
            "11234567890": "1234567890",
            "0123456789": "0123456789",
            "1423.456.7890": "4234567890",
            "0123456789.0": "0123456789",
            "9234567890abc": "9234567890",
            "1231": "",
            "asdbf": "",
        }

        for bad_phone, correct_phone in phones_to_clean.items():
            self.assertEqual(clean_phone(bad_phone), correct_phone)
