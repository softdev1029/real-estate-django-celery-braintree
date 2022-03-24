import random
import uuid

import requests
import telnyx

from django.conf import settings

from phone.choices import Provider
from sms.utils import get_webhook_url
from .BaseMessagingClient import BaseMessagingClient

telnyx.api_key = settings.TELNYX_SECRET_KEY
telnyx.max_network_retries = 2


class TelnyxClient(BaseMessagingClient):
    """
    Client to handle interactions with the telnyx api.
    """
    # Base api url for v2 api, used when sdk does not yet have the python call.
    api_url = "https://api.telnyx.com/v2"
    provider = Provider.TELNYX
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.TELNYX_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    def get_available_numbers(self, area_code, limit=30, include_mms=True, best_effort=False):
        """
        Return the available numbers for a given area code.

        :param include_mms bool: Determines whether we limit the search to only phones with MMS.

        https://developers.telnyx.com/docs/api/v2/numbers/Number-Search#listAvailablePhoneNumbers
        """
        if settings.TEST_MODE:
            # We need to fake a similar structure that we receive from the telnyx python sdk.
            payload = {
                'data': [],
                'metadata': {
                    'total_results': limit,
                },
            }
            for _ in range(limit):
                generated = ''.join([random.choice("1234567890") for _ in range(7)])
                obj = {
                    'phone_number': f'+1{area_code}{generated}',
                }
                payload['data'].append(obj)

            return payload

        features = ["sms", "voice"]
        if include_mms:
            features.append("mms")

        numbers = {
            "data": [],
            "metadata": {
                "best_effort_results": 0,
                "total_results": 0,
            },
        }
        exclude_held_numbers_choices = [True, False]
        # We want to loop while the limit has been filled or we're out of the above
        # list indexes.  The first loop will exclude held numbers and if we haven't reached
        # the limit, we'll attempt again while not excluding held numbers.
        while numbers["metadata"]["total_results"] < limit and exclude_held_numbers_choices:
            exclude_held_numbers = exclude_held_numbers_choices.pop(0)
            req = telnyx.AvailablePhoneNumber.list(
                filter={
                    "features": features,
                    "country_code": "US",
                    "limit": limit - numbers["metadata"]["total_results"],
                    "best_effort": best_effort,
                    "national_destination_code": area_code,
                    "exclude_held_numbers": [exclude_held_numbers],
                },
            )
            numbers["data"].extend(req["data"])
            numbers["metadata"]["best_effort_results"] += req["metadata"]["best_effort_results"]
            numbers["metadata"]["total_results"] += req["metadata"]["total_results"]

        return numbers

    def get_numbers(self):
        numbers_list = self.list_numbers()
        if numbers_list.status_code != 200:
            raise ValueError("Couldn't fetch phone numbers from Telnyx")
        numbers_list = numbers_list.json()["data"]

        return map(lambda x: x['phone_number'], numbers_list)

    def send_message(self, from_, to, body, media_url=None):
        """
        Send a message through telnyx[0].

        :arg from_ string: The number to send the message from, this needs to be our telnyx numer.
        :arg to string: The number to send the message to (generally the number of the prospect).
        :arg body string: The message text.
        :arg media_url string: URL to an image. Defaults to None if there's no image.

        We'll get the webhook and failover urls through our settings.

        [0] https://developers.telnyx.com/docs/v2/messaging/quickstarts/sending-sms-and-mms
        """
        if not self.is_production:
            class TelnyxFakeMessage:
                """
                Message class that returns mirrored data from the telnyx api response.
                """
                id = str(uuid.uuid4())
                to = [{'status': 'sent'}]
            return TelnyxFakeMessage

        status_webhook_url = get_webhook_url(self.provider, 'status')
        params = {
            'from_': from_,
            'to': to,
            'webhook_url': status_webhook_url,
        }
        if media_url:
            params['media_urls'] = [media_url]
        if not media_url or (media_url and 'no_text' not in body):
            params['text'] = body

        return telnyx.Message.create(**params)

    def create_messaging_profile(self, market):
        """
        Create a mesaging profile for the passed in market.

        Messaging profiles allow us to send messages through a group of numbers, and track those
        messages together.

        :arg market Market: Instance of a market.
        :return: Return the messaging profile id.
        """
        if market.messaging_profile_id:
            # If the market already has the messaging profile, just return that.
            return market.messaging_profile_id

        if not self.is_production:
            return uuid.uuid4()

        incoming_message_webhook_url = get_webhook_url(self.provider, 'incoming')

        response = telnyx.MessagingProfile.create(
            name=market.messaging_profile_name,
            webhook_url=incoming_message_webhook_url,
            number_pool_settings={
                "long_code_weight": 1,
                "toll_free_weight": 0,
                "skip_unhealthy": True,
                "sticky_sender": True,
                "geomatch": False,
            },
        )
        market.messaging_profile_id = response.id
        market.save()
        return market.messaging_profile_id

    def update_messaging_profile(self, messaging_profile_id, **kwargs):
        """
        Updates a messaging profile.

        Pass in the payload as kwargs.

        https://developers.telnyx.com/docs/api/v2/messaging/Messaging-Profiles#updateMessagingProfile
        """
        if self.is_production:
            mp = telnyx.MessagingProfile.retrieve(messaging_profile_id)
            for key in kwargs:
                setattr(mp, key, kwargs[key])
            return mp.save()

    def delete_messaging_profile(self, messaging_profile_id):
        """
        Removes a full messaging profile.

        https://developers.telnyx.com/docs/api/v2/messaging/Messaging-Profiles#deleteMessagingProfile
        """
        if self.is_production:
            mp = telnyx.MessagingProfile.retrieve(messaging_profile_id)
            return mp.delete()

    def get_message_profile_numbers(self, messaging_profile_id, page_size=250, page_number=1):
        """
        Returns the numbers associated with a messaging profile.

        https://developers.telnyx.com/docs/api/v2/messaging/Messaging-Profiles#listMessagingProfilePhoneNumbers
        """
        mp = telnyx.MessagingProfile.retrieve(messaging_profile_id)
        return mp.phone_numbers(page={"number": page_number, "size": page_size})

    def create_number_order(self, phone_numbers, messaging_profile_id=""):
        """
        Create an order to purchase a list of phone numbers for a market.

        :arg phone_numbers list: Pass in a list of full phone numbers to purchase.
        :kwarg messaging_profile_id: ID of the messaging profle that the numbers to purchase.
        """

        if not self.is_production:
            # Don't need to do anything, logic taken care of in
            # `phone_numbers.utils.process_number_order`.
            return

        phone_numbers = [{"phone_number": number} for number in phone_numbers]
        return telnyx.NumberOrder.create(
            phone_numbers=phone_numbers,
            messaging_profile_id=messaging_profile_id,
            connection_id=settings.TELNYX_CONNECTION_ID,
        )

    def update_number(self, phone_id, payload):
        """
        Updates the data about a phone number object.

        https://developers.telnyx.com/docs/api/v2/numbers/Phone-Numbers#updatePhoneNumber
        """
        if not self.is_production:
            return

        url = f"{self.api_url}/phone_numbers/{phone_id}"
        response = requests.patch(url, payload, headers=TelnyxClient.headers)
        return response

    def update_messaging_number(self, phone_id, payload):
        """
        Updates the data about a phone number object.

        This is not documented and was suggested as a workaround in the telnyx slack channel.
        """
        if not self.is_production:
            return

        url = f"{self.api_url}/phone_numbers/{phone_id}/messaging"
        response = requests.patch(url, payload, headers=TelnyxClient.headers)
        return response

    def delete_number(self, phone_id):
        """
        Delete a phone number from our telnyx account.

        :arg phone_id string: The DID identifier for the telnyx phone number.

        This is not yet available through the python sdk, so need to issue a raw request
        instead. [0]

        [0] https://developers.telnyx.com/docs/api/v2/numbers/Phone-Numbers#deletePhoneNumber
        """
        if not self.is_production:
            return

        url = f"{self.api_url}/phone_numbers/{phone_id}"
        response = requests.delete(url=url, headers=TelnyxClient.headers)
        return response

    def list_numbers(self, page_size=250, messaging_profile_id='', phone_number='', status=None,
                     page_number=None):
        """
        List all of the messaging numbers that we have in the telnyx system.

        :param messaging_profile_id str: Filter the numbers for the passed in messaging profile.
        :param status str: Filter the numbers for the given status.
        :return:

        https://developers.telnyx.com/docs/api/v2/numbers/Phone-Numbers#findPhoneNumbers
        """
        from sherpa.models import Market, PhoneNumber

        if not self.is_production:
            class TelnyxFakeResponse:
                # Return a fake response object mimicing the used response data from Telnyx.
                status_code = 200

                def json():
                    data = {}
                    market = Market.objects.get(messaging_profile_id=messaging_profile_id)
                    numbers = PhoneNumber.objects.filter(market=market)
                    for instance in numbers:
                        data['phone_number'] = instance.phone
                        data['id'] = round(random.random() * 100000000)
                        data['status'] = 'active'

                    return {'data': [data]}

            return TelnyxFakeResponse

        # Build up the url, not suppported yet in sdk.
        url = f"{self.api_url}/phone_numbers/"
        url += f"?page[size]={page_size}"

        # Apply the filters that were passed in.
        if messaging_profile_id:
            url += f"&filter[messaging.messaging_profile_name][eq]={messaging_profile_id}"
        if status:
            url += f"&filter[status]={status}"
        if phone_number:
            url += f"&filter[phone_number]={phone_number}"

        # Return the response of the filtered message number list.
        return requests.get(url, headers=TelnyxClient.headers)

    def messaging_phone_numbers(self, page_size=250, page_number=1):
        """
        List all messaging capable phone numbers

        https://developers.telnyx.com/docs/api/v2/messaging/Phone-Numbers?lang=curl#updateMessagingPhoneNumber
        """
        url = f"{self.api_url}/messaging_phone_numbers"
        url += f"?page[size]={page_size}&page[number]={page_number}"

        return requests.get(url, headers=TelnyxClient.headers)

    def retrieve_call(self, call_control_id):
        """
        Retrieve a call object, allowing us to control the flow.

        https://developers.telnyx.com/docs/api/v2/call-control/Call-Information
        """
        if not self.is_production:
            class TelnyxFakeCall:
                call_session_id = uuid.uuid4()
                data = {
                    "record_type": "call",
                    "call_session_id": call_session_id,
                    "call_leg_id": call_session_id,
                    "call_control_id": call_control_id,
                    "is_alive": True,
                }
            return TelnyxFakeCall

        return telnyx.Call.retrieve(call_control_id)

    def transfer_call(self, call_control_id, from_number, to_number):
        url = self.api_url + f'/calls/{call_control_id}/actions/transfer'
        payload = {
            "to": to_number,
            "from": from_number,
        }
        return requests.post(url, payload, headers=TelnyxClient.headers)

    @staticmethod
    def create_c2c_token():
        """
        Calls Telnyx to generate a JWT token to use during WebRTC authentication.

        Note:  The settings.TELNYX_CREDENTIAL_ID is a credential that was created utilizing the SIP
        connection ID.  This value has an expire date of 30 years.

        https://developers.telnyx.com/docs/api/v2/webrtc
        """
        cred_id = settings.TELNYX_CREDENTIAL_ID
        res = requests.post(
            f"https://api.telnyx.com/v2/telephony_credentials/{cred_id}/token",
            headers=TelnyxClient.headers,
        )
        return res.text if res.status_code == 201 else None
