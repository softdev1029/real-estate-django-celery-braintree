from datetime import timedelta
import uuid

from model_mommy import mommy
from telnyx.error import APIError

from django.urls import reverse
from django.utils import timezone as django_tz

from sherpa.tests import BaseAPITestCase


class TestSMSClient:
    """
    Mock SMS client.
    """
    def __init__(self):
        self.is_production = True


class TestTelnyxCall:
    """
    Mock Telnyx Call object
    """
    def __init__(self, error_code):
        self.error_code = error_code

    def transfer(self, *args, **kwargs):
        """
        Mock call transfer.
        """
        if self.error_code:
            raise APIError(json_body={'errors': [{'code': self.error_code}]})
        return


class CallAPITestCase(BaseAPITestCase):
    call_url = reverse('call-list')
    call_webhook_url = reverse('call-received-telnyx')

    def setUp(self):
        super(CallAPITestCase, self).setUp()
        self.market = mommy.make('sherpa.Market', company=self.company1)
        self.phone_number = mommy.make(
            'sherpa.PhoneNumber',
            company=self.company1,
            market=self.market,
        )
        self.prospect = mommy.make(
            'sherpa.Prospect',
            phone_raw='2066667777',
            company=self.company1,
            first_name='Luke',
            last_name='Skywalker',
        )
        self.campaign = mommy.make('sherpa.Campaign', company=self.company1, market=self.market)
        self.campaign_prospect = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.prospect,
            campaign=self.campaign,
        )

        now = django_tz.now()
        mommy.make(
            'calls.Call',
            prospect=self.prospect,
            agent_profile=self.george_user.profile,
            to_number=self.prospect.phone_raw,
            from_number="",
            start_time=now - timedelta(minutes=5),
            end_time=now,
        )
        now -= timedelta(days=5)
        mommy.make(
            'calls.Call',
            prospect=self.prospect,
            agent_profile=self.george_user.profile,
            to_number=self.prospect.phone_raw,
            from_number="",
            start_time=now - timedelta(minutes=10),
            end_time=now,
        )
        self.call = mommy.make(
            'calls.Call',
            prospect=self.prospect,
            agent_profile=self.george_user.profile,
            to_number=self.prospect.phone_raw,
            from_number="",
            start_time="2020-02-11 01:08:12.709000+00:00",
            end_time="2020-02-11 01:08:19.709000+00:00",
        )

    def __generate_webhook_data(
        self,
        event_type,
        call_control_id=uuid.uuid4(),
        call_session_id=uuid.uuid4(),
        to_number='+12025550131',
        from_number='+12025550133',
        start_time=django_tz.now(),
        end_time=None,
    ):
        """
        Return a faked version of data that would be sent from the webhook.
        """
        class FakeWebhookRequest:
            data = {
                "record_type": "event",
                "event_type": "call.initiated",
                "id": uuid.uuid4(),
                "occurred_at": django_tz.now(),
                "payload": {
                    "call_control_id": call_control_id,
                    "connection_id": "7267xxxxxxxxxxxxxx",
                    "call_leg_id": uuid.uuid4(),
                    "call_session_id": call_session_id,
                    "client_state": "aGF2ZSBhIg5pY2UgZGF5ID1d",
                    "from": from_number,
                    "to": to_number,
                    "direction": "incoming",
                    "state": "parked",
                    "start_time": start_time,
                    "end_time": end_time,
                },
            }

        return FakeWebhookRequest()

    # def test_catch_if_no_sherpa_phone(self):
    #     payload = self.__generate_webhook_data('call_initiated').data
    #     response = self.client.post(self.call_webhook_url, payload)
    #     self.assertEqual(response.status_code, 400)
    #     self.assertTrue('No sherpa phone found' in response.json().get('detail'))

    #     # Verify that the call's error was saved.
    #     call = Call.objects.first()
    #     self.assertEqual(call.error, Call.ErrorType.NO_SHERPA_PHONE)

    # def test_catch_if_no_prospect(self):
    #     payload = self.__generate_webhook_data(
    #         'call_initiated',
    #         to_number=self.phone_number.phone,
    #     ).data
    #     response = self.client.post(self.call_webhook_url, payload)
    #     self.assertEqual(response.status_code, 400)
    #     self.assertTrue('No prospect relation found for a call' in response.json().get('detail'))

    #     # Verify that the call's error was saved.
    #     call = Call.objects.first()
    #     self.assertEqual(call.error, Call.ErrorType.NO_PROSPECT)
    #     self.assertEqual(call.sherpa_phone, self.phone_number)

    # def test_catch_if_no_forwarding_number(self):
    #     payload = self.__generate_webhook_data(
    #         'call_initiated',
    #         to_number=self.phone_number.phone,
    #         from_number=f'+1{self.prospect.phone_raw}'
    #     ).data
    #     response = self.client.post(self.call_webhook_url, payload)
    #     self.assertEqual(response.status_code, 400)
    #     self.assertTrue('No forwarding' in response.json().get('detail'))

    #     # Verify that the call's error was saved.
    #     call = Call.objects.first()
    #     self.assertEqual(call.error, Call.ErrorType.NO_FORWARDING)
    #     self.assertEqual(call.prospect, self.prospect)

    # def test_can_receive_call_webhook(self):
    #     self.market.call_forwarding_number = '5092228888'
    #     self.market.save()

    #     payload = self.__generate_webhook_data(
    #         'call_initiated',
    #         to_number=self.phone_number.phone,
    #         from_number=f'+1{self.prospect.phone_raw}'
    #     ).data

    #     response = self.client.post(self.call_webhook_url, payload)
    #     self.assertEqual(response.status_code, 200)

    #     # Verify everything is good with the call object at this point.
    #     call = Call.objects.first()
    #     self.assertEqual(call.forwarded_number, self.prospect.call_forwarding_number)

    #     # Verify that end_time and duration are saved.
    #     payload = self.__generate_webhook_data(
    #         'call_hangup',
    #         to_number=self.prospect.call_forwarding_number,
    #         from_number=f'+1{self.prospect.phone_raw}',
    #         end_time=django_tz.now(),
    #     ).data
    #     response = self.client.post(self.call_webhook_url, payload)
    #     self.assertEqual(response.status_code, 200)
    #     call.refresh_from_db()
    #     self.assertTrue(call.duration >= 0)
    #     self.assertNotEqual(call.end_time, None)

    def test_unauthenticated_user(self):
        """
        The webhook URL should be accessible to anyone but the logging should be hidden.
        """
        response = self.client.get(self.call_url)
        self.assertEqual(response.status_code, 401)
        response = self.client.get(self.call_webhook_url)
        self.assertEqual(response.status_code, 405)

    def test_call_log_create(self):
        now = django_tz.now()
        payload = {
            "toNumber": f"+1{self.prospect.phone_raw}",
            "prospect": self.prospect.pk,
            "startTime": (now - timedelta(minutes=5)).isoformat(),
            "endTime": now.isoformat(),
        }
        response = self.george_client.post(self.call_url, payload)
        self.assertEqual(response.status_code, 201)

    def test_call_forwarding_inactive_call_errors(self):
        """
        Test handling calls that are no longer active during forwarding.
        """
        client = TestSMSClient()
        test_call = TestTelnyxCall(error_code='90018')
        self.call.forward(client, test_call, '123456789')

        self.assertEqual(self.call.error, self.call.ErrorType.CALL_INACTIVE)

        # If the error code is'nt 90018, we should save the default error.
        test_call.error_code = '12345'
        self.call.forward(client, test_call, '123456789')

        self.assertEqual(self.call.error, self.call.ErrorType.TELNYX_API_ERROR)

    # TODO (aww20200812) Removing this test as it is flaky and sometimes fails, possibly related to
    # time of day.

    # def test_call_log_results(self):
    #     now = django_tz.now()
    #     # Should return 0
    #     date_filter = {
    #         'start_date': (now - timedelta(days=1)).date().isoformat(),
    #         'end_date': (now - timedelta(days=1)).date().isoformat(),
    #     }

    #     response = self.george_client.get(self.call_url, date_filter)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get('count'), 0)

    #     # Should return 1
    #     date_filter = {
    #         'start_date': now.date().isoformat(),
    #         'end_date': now.date().isoformat(),
    #     }

    #     response = self.george_client.get(self.call_url, date_filter)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get('count'), 1)
    #     self.assertEqual(response.json().get('results')[0]['duration'], 300)

    #     # Should return 1
    #     date_filter = {
    #         'start_date': (now - timedelta(days=5)).date().isoformat(),
    #         'end_date': (now - timedelta(days=5)).date().isoformat(),
    #     }

    #     response = self.george_client.get(self.call_url, date_filter)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get('count'), 1)
    #     self.assertEqual(response.json().get('results')[0]['duration'], 600)

    #     # Should return 2
    #     response = self.george_client.get(self.call_url)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get('count'), 2)

    #     # Should return 1 checking via local timezone.
    #     date_filter = {
    #         'start_date': '2020-02-10',
    #         'end_date': '2020-02-10',
    #     }
    #     response = self.george_client.get(self.call_url, date_filter)
    #     self.assertEqual(response.status_code, 200)
    #     self.assertEqual(response.json().get('count'), 1)
