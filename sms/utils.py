import os
import re

from django.conf import settings
from django.contrib.sites.models import Site
from django.urls import reverse
from rest_framework.response import Response

from core.utils import clean_phone
from phone.choices import Provider
from sms import VALID_TAGS


def get_tags(message):
    """
    Return all the tags that are used in a message string.
    """
    pattern = r'(?<=\{)([^]]*?)(?=\})'
    tags = re.findall(pattern, message, re.IGNORECASE)

    # Remove all the Tag:N which specifies which index to pull the tag value from.
    return [tag.split(':', 1)[0] for tag in tags]


def all_tags_valid(message):
    """
    Return Boolean indicating if all the message's tags are valid.
    """
    return all([
        message.count('{') == message.count('}'),
        all([tag in VALID_TAGS for tag in get_tags(message)]),
    ])


def has_tag(message, tag):
    return tag in get_tags(message)


def find_banned_words(message):
    """
    Returns a list of any banned words that are in the template message.
    """
    search = '|'.join([f'\\b{word}\\b' for word in settings.BANNED_WORDS])
    return re.findall(search, message, re.IGNORECASE)


def find_spam_words(message):
    """
    Returns a list of any spam words/phrases that are in the template message.
    """
    search = '|'.join([f'\\b{word}\\b' for word in settings.SPAM_WORDS])
    return re.findall(search, message, re.IGNORECASE)


def get_webhook_url(provider, webhook_type):
    """
    Return the fully qualified telnyx webhook url to attach to messages.

    :provider string: Either telnyx or twilio.
    :webhook_type string: Type of webhook we're getting. Choices are `incoming` or `status`.

    We can override this by supplying the `NGROK_URL` instead of using the django site.
    """

    if provider not in [val[0] for val in Provider.CHOICES]:
        raise Exception(f'Received invalid provider for webhook url: `{provider}`.')

    ngrok_url = os.getenv('NGROK_URL')
    if ngrok_url:
        domain = f'http://{ngrok_url}'
    else:
        if provider == Provider.TELNYX:
            domain = Site.objects.get(id=settings.TELNYX_TELEPHONY_SITE_ID).domain
        else:
            domain = settings.TELEPHONY_WEBHOOK_DOMAIN

    webhook_url = ""
    if webhook_type == 'status':
        webhook_url = reverse(f'smsresult-{provider}')
    elif webhook_type == 'incoming':
        webhook_url = reverse(f'smsmessage-received-{provider}')
    elif webhook_type == 'voice':
        webhook_url = reverse(f'call-received-{provider}')

    return domain + webhook_url


def get_webhook_phone_instance(phone_number):
    """
    Return an instance of `PhoneNumber` from the phone number.
    """
    from sherpa.models import PhoneNumber

    phone_raw = clean_phone(phone_number)
    twilio_phone_record = PhoneNumber.objects.filter(
        phone=phone_raw,
        status=PhoneNumber.Status.ACTIVE,
    ).first()

    if not twilio_phone_record:
        # The phone number that sent the message does not exist in our system.
        error = (f'Attempted lookup of `{phone_raw}`, which is not an active number. '
                 'This probably came from a status or message webhook.')
        raise Exception(error)

    return twilio_phone_record


def handle_telnyx_view_error(error):
    """
    Receives an error instance and attempts to return a response which will then be relayed as the
    error message. If a valid response can't be returned, then raise the error.
    """
    error_data_list = error.json_body.get('errors')
    if not error_data_list:
        raise error

    error_data = error_data_list[0]
    error_code = error_data.get('code')
    error_detail = error_data.get('detail')
    return Response(
        {'detail': f'Failed to send: {error_detail} ({error_code})'},
        status=400,
    )


def telnyx_error_has_error_code(exception, error_code):
    errors = exception.json_body.get('errors') or []

    for error in errors:
        if error.get('code', '') == error_code:
            return True

    return False


def fetch_phonenumber_info(phonenumber: str):
    from sms.clients import get_client
    client = get_client()
    return client.fetch_number(phonenumber)
