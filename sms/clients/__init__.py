from companies.models import TelephonyConnection
from phone.choices import Provider
from .InteliquentClient import InteliquentClient
from .TelnyxClient import TelnyxClient
from .TwilioClient import TwilioClient

__all__ = ('get_client',)


def get_client(provider='any', key=None, secret=None, company_id=None):
    """
    Returns the client for the given provider.
    :param provider: The provider to connect to. Use default 'any' if the provider doesn't matter.
    :param key: API key (if using anything other than default)
    :param secret: API secret (if using anything other than default)
    :param company_id: The company id, only needed if not directly passing the API key/secret
    """

    if provider == Provider.TELNYX or provider == 'any':
        return TelnyxClient()

    elif provider == Provider.INTELIQUENT:
        return InteliquentClient()

    elif provider == Provider.TWILIO:
        if key and secret:
            return TwilioClient(key, secret)
        elif company_id is not None:
            connection = TelephonyConnection.objects.filter(
                company_id=company_id,
                provider=Provider.TWILIO,
            )
            if connection.exists():
                return connection.first().client
            else:
                return None
        else:
            return TwilioClient()
