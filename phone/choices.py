class Provider:
    """
    Static values for the phone providers that we support.
    """
    TWILIO = 'twilio'
    TELNYX = 'telnyx'
    INTELIQUENT = 'inteliquent'

    CHOICES = (
        (TWILIO, 'Twilio'),
        (TELNYX, 'Telnyx'),
        (INTELIQUENT, 'Inteliquent'),
    )

    NAME_LOOKUP = dict((value, key) for (key, value) in CHOICES)

    DEFAULT = TELNYX

    SMS_MARKET_MINIMUM_DEFAULT = 20

    SMS_MARKET_MINIMUM = {
        TWILIO: SMS_MARKET_MINIMUM_DEFAULT,
        TELNYX: SMS_MARKET_MINIMUM_DEFAULT,
        INTELIQUENT: 5,
    }

    # If above 20, users get suspended
    assert(SMS_MARKET_MINIMUM[TWILIO] <= 20)

    @staticmethod
    def get(provider_id: int):
        assert(isinstance(int(provider_id), int))

        if int(provider_id) >= len(Provider.CHOICES):
            return Provider.DEFAULT

        return Provider.CHOICES[provider_id][0]

    @staticmethod
    def get_by_name(provider_name: str):
        return Provider.NAME_LOOKUP.get(provider_name, Provider.DEFAULT)

    @staticmethod
    def get_market_minimum(provider: str):
        """
        Minimum number of phones required by this Provider
        """
        assert(provider in dict(Provider.CHOICES))
        return Provider.SMS_MARKET_MINIMUM.get(provider, Provider.SMS_MARKET_MINIMUM_DEFAULT)


class PhoneLineType:
    """
    Static values for phone types.
    """
    LANDLINE = 'landline'
    MOBILE = 'mobile'
    VOIP = 'voip'

    CHOICES = (
        (LANDLINE, 'Landline'),
        (MOBILE, 'mobile'),
        (VOIP, 'voip'),
    )
