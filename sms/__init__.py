from telnyx.error import (
    APIError,
    InvalidParametersError,
    InvalidRequestError,
    PermissionError as TelnyxPermissionError,
)

# Maps a tag to the instance property.
TAG_MAPPINGS = {
    'FirstName': 'first_name',
    'LastName': 'last_name',
    'StreetAddress': 'property_address',
    'PropertyStreetAddress': 'property_address',
    'PropertyAddressFull': 'address_display',
    'City': 'property_city',
    'State': 'property_state',
    'ZipCode': 'property_zip',
    'Custom1': 'custom1',
    'NAME': 'first_name',
    'ADDRESS': 'property_address',
    'CompanyName': None,
    'UserFirstName': None,
}


# List of tags that are valid for merging into sms templates or quick replies.
VALID_TAGS = list(TAG_MAPPINGS.keys())

OPT_OUT_LANGUAGE = " Reply STOP for opt-out."
OPT_OUT_LANGUAGE_TWILIO = " reply stop to end."

# A full list of telnyx errors that we want to handle. Sometimes we'll only want to catch some of
# them, but in many cases we will catch all.
TELNYX_ERRORS_FULL = (
    APIError,
    InvalidRequestError,
    InvalidParametersError,
    TelnyxPermissionError,
)
