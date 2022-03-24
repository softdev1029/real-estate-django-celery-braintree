import uuid

from twilio.rest import Client as TwilioRestClient

from phone.choices import Provider
from sms.utils import get_webhook_url
from .BaseMessagingClient import BaseMessagingClient


class TwilioClient(BaseMessagingClient):
    """
    Twilio client class to handle all actions in sherpa with twilio.
    """
    provider = Provider.TWILIO

    def __init__(self, twilio_sid=None, twilio_private_token=None):
        """
        Pass in the credentials to use for the default twilio client.
        Companies use their own twilio account with different credentials.
        """
        self.client = TwilioRestClient(twilio_sid, twilio_private_token)
        super().__init__()

    def get_available_numbers(self, area_code):
        """
        Return the available numbers for a given area code.

        TODO (aww20190924) should filter this list to make sure the number doesn't already exist
        in the sherpa system, instead of filtering downstream when purchasing the numbers.
        """
        return self.client.available_phone_numbers("US").local.list(area_code=area_code)

    def get_numbers(self):
        """
        Get all numbers in this account.
        """
        return self.client.incoming_phone_numbers.list()

    def send_message(self, **kwargs):
        """
        Send message is the only action that we use the environment twilio credentials instead of
        production, so that the message doesn't actually get sent.

        If sending a message in test we need to send from the twilio magic number. [0]

        [0] https://www.twilio.com/docs/iam/test-credentials#test-sms-messages
        """
        if not self.is_production:
            class TwilioFakeMessage:
                """
                Message class that returns mirrored data from the twilio api response.
                """
                sid = str(uuid.uuid4())
                status = 'completed'

            return TwilioFakeMessage

        # Only apply the status callback if in production.
        kwargs['status_callback'] = get_webhook_url(self.provider, 'status')
        response = self.client.messages.create(**kwargs)
        return response

    def purchase_number(self, phone_number):
        """
        Purchase a phone number from twilio.

        For testing we'll create an empty object just with the properties we need, mimicking the
        actual object. We are not currently purchasing Twilio numbers, but just using what is setup
        for the client.
        """
        return False

    def delete_number(self, twilio_sid):
        """
        Delete a number from twilio.

        For test purposes we won't do anything in twilio.
        """
        if self.is_production:
            return self.client.incoming_phone_numbers(twilio_sid).delete()

    def update_number(self, twilio_sid, **kwargs):
        """
        Update data for a twilio number, this is usually called after purchasing a number.
        """
        return self.client.incoming_phone_numbers(twilio_sid).update(**kwargs)
