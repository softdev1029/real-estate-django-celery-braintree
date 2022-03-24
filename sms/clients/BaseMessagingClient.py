from abc import ABC, abstractmethod

import requests

from django.conf import settings
from django.core.exceptions import ValidationError

from sms.utils import clean_phone


class BaseMessagingClient(ABC):
    """
    Base client to handle all shared functionality between our various provider clients.

    :prop is_production bool: Determines if we're actually using the live API. Generally for the
        non-read operations we'll first check if we're not in production and then fake the data
        response.
    """
    is_production = settings.USE_TEST_MESSAGING is False

    def __init__(self, is_production=None):
        """
        :param is_production bool: Optionally override the is_production setting.
        """
        if is_production is not None:
            self.is_production = is_production

    def fetch_number(self, phone_number_raw, raise_errors=False):
        """
        Always use telnyx for phone lookups because it is free.

        :phone_number string: Phone number with country code prefix.
        :raise_errors bool: Indicates if we should stop for errors.
        :return: dictionary of the response data.

        Manual test URL: https://telnyx.com/number-lookup
        API docs: https://developers.telnyx.com/docs/api/v2/number-lookup/Number-Lookup
        """
        phone_number = clean_phone(phone_number_raw)
        if not phone_number and raise_errors:
            raise ValidationError(f"{phone_number_raw} is not a 10 digit phone number.")

        url = f'https://api.telnyx.com/v2/number_lookup/+1{phone_number}?carrier'
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {settings.TELNYX_SECRET_KEY}',
        }

        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 422 and raise_errors:
            raise ValidationError(response.json().get('details'))

        if response.status_code != 200:
            if raise_errors:
                # Telnyx is unexpectedly down. API docs 'default' unexpected.
                raise ConnectionError()
            # We don't want to kill an entire upload due to the service being down.
            return {
                'name': 'na',
                'type': 'na',
            }
        data = response.json()['data']['portability']
        return {
            'name': data['spid_carrier_name'],
            'type': data['line_type'] if data['line_type'] != "fixed line" else "landline",
        }

    @abstractmethod
    def get_available_numbers(self, area_code):
        raise NotImplementedError("Provider must implement get_available_numbers")

    @abstractmethod
    def get_numbers(self):
        raise NotImplementedError("Provider must implement get_numbers")

    @abstractmethod
    def send_message(self, from_, to, body, media_url=None):
        raise NotImplementedError("Provider must implement send_message")
