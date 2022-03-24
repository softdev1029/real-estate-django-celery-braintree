from requests.exceptions import ConnectTimeout

from django.core.exceptions import ValidationError

from phone.choices import PhoneLineType
from sms.clients import TelnyxClient


def validate_mobile_or_landline(phone):
    """
    Validate phone is either landline or mobile.
    """

    client = TelnyxClient()
    try:
        carrier_data = client.fetch_number(phone, raise_errors=True)
    except (ConnectTimeout, ConnectionError):
        raise ValidationError("Phone check provider is down. Please try again later.")

    phone_type = carrier_data['type']

    if phone_type in [PhoneLineType.LANDLINE, PhoneLineType.MOBILE]:
        return phone
    else:
        raise ValidationError("Must be a valid mobile or landline phone.")
