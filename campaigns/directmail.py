from .directmail_clients import AccuTraceClient, YellowLetterClient


def yellow_letter_record_formatter(records, return_address):
    """
    Return records formatted for Yellow Letter API.
    """
    from campaigns.serializers import YellowLetterSerializer

    address = return_address.address
    context = {
        'full_name': '',
        'agent_name': f'{return_address.first_name} {return_address.last_name}',
        'agent_number': return_address.phone,
        'return_address_street': address.address,
        'return_address_zip': f'{address.city}, {address.state} {address.zip_code}',
    }

    fix_blank_mailing_address(records.filter(prop__mailing_address__isnull=True))
    serializer = YellowLetterSerializer(records, many=True, context=context)
    serializer_data = serializer.data
    resp_data = update_mailing_address(records, serializer_data, DirectMailProvider.YELLOWLETTER)

    return resp_data


def fix_blank_mailing_address(prospects):
    """
    Copy property address over to mailing address when mailing address is blank.
    """
    for prospect in prospects.all():
        if not prospect.prop.mailing_address:
            prospect.prop.mailing_address = prospect.prop.address
            prospect.prop.save(update_fields=['mailing_address'])


def update_mailing_address(records, serializer_data, provider):
    """
    Update mailing address with Golden Address if Company has Direct Mail Golden Address enabled.
    """
    resp_data = serializer_data
    address_keys = DirectMailProvider.MAILING_FIELD_NAMES[provider]

    if records.exists():
        company = records[0].prop.company
        if company.enable_dm_golden_address:
            resp_data = []
            for an_formated_resp, an_prospect in zip(serializer_data, records):
                skip_trace_prop = an_prospect.prop.skiptraceproperty_set.all()
                if skip_trace_prop.exists():
                    for an_address in skip_trace_prop:
                        golden_address = an_address.golden_address_lines
                        if golden_address:
                            an_formated_resp[address_keys['street']] = golden_address
                            an_formated_resp[address_keys['city']] = an_address.golden_city
                            an_formated_resp[address_keys['state']] = an_address.golden_state
                            an_formated_resp[address_keys['zip']] = an_address.golden_zipcode
                            break
                resp_data.append(an_formated_resp)
    return resp_data


class YellowLetterTemplates:
    S123 = 'S123'
    S124 = 'S124'
    S128 = 'S128'
    S126 = 'S126'
    S127 = 'S127'

    CHOICES = (
        (S123, 'Doodle'),
        (S124, 'Standard'),
        (S128, 'Street View'),
        (S126, 'Blessed'),
        (S127, 'Orange Crush'),
    )


class DirectMailProvider:
    """
    Static values for the direct mail providers that we support.
    """
    YELLOWLETTER = 'yellowletter'

    CHOICES = (
        (YELLOWLETTER, 'Yellow Letter'),
    )

    FORMATTER = {
        YELLOWLETTER: yellow_letter_record_formatter,
    }

    CLIENTS = {
        YELLOWLETTER: YellowLetterClient(),
    }

    TRACKING_CLIENTS = AccuTraceClient()

    TEMPLATES = {
        YELLOWLETTER: YellowLetterTemplates.CHOICES,
    }

    MAILING_FIELD_NAMES = {
        YELLOWLETTER: {
            'street': 'MailingAddress',
            'city': 'Mailingcity',
            'state': 'MailingState',
            'zip': 'Mailingzip',
        },
    }
