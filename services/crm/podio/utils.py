import datetime
from functools import wraps

from dateutil import parser
from pypodio2 import transport

from companies.resources import PodioResource
from sherpa.models import Prospect


class OAuthAuthorizationFromTokens(object):
    """Generates headers for Podio OAuth2 with existing access/refresh tokens"""
    def __init__(self, tokens):
        self.token = transport.OAuthToken({
            'access_token': tokens.get('access'),
            'refresh_token': tokens.get('refresh'),
            'expires_in': tokens.get('expires_in'),
        })

    def __call__(self):
        return self.token.to_headers()


def refresh(method):
    """allows us to apply refresh token logic functionality to our methods"""
    @wraps(method)
    def _impl(self, *method_args, **method_kwargs):
        try:
            return method(self, *method_args, **method_kwargs)
        except transport.TransportException as e:
            # handle cases:
            # - rate limited
            if e.status['status'] == 420:
                pass
            elif e.status['status'] == 401:
                # refresh logic
                self._refresh_handler()
                return method(self, *method_args, **method_kwargs)
            raise transport.TransportException(e.status, e.content) from None
    return _impl


def for_all_methods(decorator):
    """Allows us to apply a decorator to the methods of the class that's being decorated
    """
    def decorate(cls):
        for attr in cls.__dict__:  # there's propably a better way to do this
            if not attr.startswith("_") and callable(getattr(cls, attr)):
                setattr(cls, attr, decorator(getattr(cls, attr)))
        return cls
    return decorate


def response_handler(method):
    """Transform all results to a common interface"""
    @wraps(method)
    def _impl(self, *method_args, **method_kwargs):
        status, response = method(self, *method_args, **method_kwargs)
        return {'response': {'data': response}, 'status': status}
    return _impl


def to_podio_phone_field(source, fields, config):
    """
    Helper function that selects data from `source` based on the values
    `fields`. Transform the data selected to the appropriate interface, for
    phone field, that the Podio API finds acceptable.

    :param source PodioResource: Exported data extracted from PodioResource
    :param fields json: The current mapped fields being processed. Potentially
                        contains multiple mapped fields.
    :param config json: Contains meta-data from sherpa fields
    """
    phone_type_mapping = 'phone_1_type'
    possible_phone_types = config.get('settings', {}).get('possible_types', [])
    default_value = config.get('default_value', '')
    phone_type = "other"
    phone = " ".join([
        source[field] for field in fields
        if not field == phone_type_mapping and source[field]
    ])

    # NOTE: Podio has restrictions on what phone-types can be passed
    # Only 1 or 2 of our phone-types map to podio
    # Guard against values from our data against the possible podio phone-type list
    if phone_type_mapping in fields:
        _phone_type = source.get(phone_type_mapping, 'other')
        phone_type = _phone_type if _phone_type in possible_phone_types else 'other'

    return {
        'type': phone_type,
        'value': phone if phone.strip() else default_value,
    }


def to_podio_email_field(source, fields, config):
    """
    Helper function that selects data from `source` based on the values
    `fields`. Transform the data selected to the appropriate interface, for
    email field, that the Podio API finds acceptable.

    :param source PodioResource: Exported data extracted from PodioResource
    :param fields json: The current mapped fields being processed. Potentially
                        contains multiple mapped fields.
    :param config json: Contains meta-data from sherpa fields
    """
    values = [source[field] for field in fields if source[field]]

    # if there are no values then we need to return a falsy value
    # to avoid adding it to the fields we want to export
    if not values:
        return None

    return {
        "type": "other",
        "value": " ".join(values),
    }


def to_podio_date_field(source, fields, config):
    """
    Helper function that selects data from `source` based on the values
    `fields`. Transform the data selected to the appropriate interface, for
    date field, that the Podio API finds acceptable.

    :param source PodioResource: Exported data extracted from PodioResource
    :param fields json: The current mapped fields being processed. Potentially
                        contains multiple mapped fields.
    :param config json: Contains meta-data from sherpa fields
    """
    default_value = config.get('default_value', '')
    # By this point the date/datetime has already been converted to a string by PodioResource
    str_date_value = source.get(fields[0], default_value)
    if not str_date_value:
        return None

    # Recovering the date as a datetime and creating the date data object as Podio requires it
    dt_value = parser.parse(str_date_value)
    data = {
        'start_date': str(dt_value.date()),
    }
    # If the datetime includes a non zero timestamp, its added to the podio date data object
    if dt_value.time() != datetime.time(0, 0):
        data['start_time'] = f'{dt_value.hour:02d}:{dt_value.minute:02d}:{dt_value.second:02d}'
    return data


ADDRESS_ADDRESS = "address_address"
ADDRESS_CITY = "address_city"
ADDRESS_STATE = "address_state"
ADDRESS_ZIP = "address_zip"


def has_zip_and_state(fields):
    return ADDRESS_STATE in fields and ADDRESS_ZIP in fields


def get_value_for_2_fields(source, fields):
    if has_zip_and_state(fields):
        state = source[fields[0]]
        zipcode = source[fields[1]]
        return f"{state} {zipcode}"

    # no zip and state combined we can add commas in between
    return ", ".join([source[field] for field in fields])


def get_value_for_3_fields(source, fields):
    if has_zip_and_state(fields):
        [some_field_key, state_key, zipcode_key] = fields
        field = source[some_field_key]
        state = source[state_key]
        zipcode = source[zipcode_key]
        return f"{field}, {state} {zipcode}"

    # no zip and state combined we can add commas in between
    return ", ".join([source[field] for field in fields])


def get_value_for_4_fields(source, fields):
    [address_key, city_key, state_key, zipcode_key] = fields
    address = source[address_key]
    city = source[city_key]
    state = source[state_key]
    zipcode = source[zipcode_key]

    return f"{address}, {city}, {state} {zipcode}"


def to_podio_address_field(source, fields, config):
    """
    Helper function that selects data from `source` based on the values
    `fields`. Transform the data selected to the appropriate interface, for
    most fields that aren't structured, that the Podio API finds acceptable.
    :param source PodioResource: Exported data extracted from PodioResource
    :param fields json: The current mapped fields being processed. Potentially
                        contains multiple mapped fields.
    :param config json: Contains meta-data from sherpa fields
    """
    address_fields = [ADDRESS_ADDRESS, ADDRESS_CITY, ADDRESS_STATE, ADDRESS_ZIP]
    value = None

    if fields and all([field in address_fields for field in fields]):
        sorted_fields = sorted(fields)
        length = len(sorted_fields)
        if length == 2:
            value = get_value_for_2_fields(source, sorted_fields)
        elif length == 3:
            value = get_value_for_3_fields(source, sorted_fields)
        elif length == 4:
            value = get_value_for_4_fields(source, sorted_fields)
        else:
            # export only 1 field
            value = source[fields[0]]
    else:
        value = ", ".join([source[field] for field in fields if source[field]])

    # if there are no values then we need to return a falsy value
    # to avoid adding it to the fields we want to export
    if not value:
        return None

    return value


def default_export_field(source, fields, config):
    return " ".join([source[field] for field in fields if source[field]])


# Dictionary that creates a mapping from field-type => field-function
field_create_fns = {
    'phone': to_podio_phone_field,
    'address': to_podio_address_field,
    'date': to_podio_date_field,
    'email': to_podio_email_field,
}


def fetch_data_to_sync(mappings, meta_data, prospect=None):
    """
    Fetches and transform the data that needs to be synced to podio
    based on the mappings.

    :param mappings dict: Dictionary containing the mapped fields
    :param meta_data dict: Contains information about the prospect being
                           synced
    """
    prospect_id = meta_data.get('prospect_id')
    prospect_inst = Prospect.objects.get(pk=int(prospect_id))
    prospect_data = prospect or PodioResource().export_resource(prospect_inst)
    data = {}

    # translate the sherpa field to podio-field
    field_mappings = mappings.fields
    for key in field_mappings:
        mapping = field_mappings[key]
        fields = mapping.get('value', {})

        if isinstance(fields, list):
            config = mapping.get('config', {})
            field_type = config.get('field_type', '')
            create_field_fn = field_create_fns.get(field_type, default_export_field)
            value = create_field_fn(prospect_data, fields, config)

            # don't inject the key for date-fields if the value is blank on our db
            if not value:
                continue

            data[key] = value
        elif mapping.get('is_category'):
            data[key] = fields
        else:
            # assume it's a dict
            data[key] = fields.get('value', '')

    return {'fields': data}
