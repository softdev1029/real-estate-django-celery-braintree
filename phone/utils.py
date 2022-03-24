import uuid

from sherpa.models import PhoneNumber
from sms.clients import TelnyxClient
from .choices import Provider


def process_number_order(market, phone_number_list):
    """
    Create a number order in Telnyx and also create the data in Sherpa.

    :arg market Market: Instance of a market to create the phone numbers for.
    :arg phone_number_list list: List of fully qualified phone numbers.
    """
    from markets.tasks import update_pending_numbers

    # This is Telnyx specific. We will need to look at this again when refactoring to make scalable.
    if market.phone_provider == Provider.TWILIO:
        return

    # This is currently only used for testing purposes
    if market.phone_provider == Provider.INTELIQUENT:
        add_numbers(market, PhoneNumber.Status.ACTIVE, phone_number_list, production=False)
        return

    client = TelnyxClient()
    client.create_number_order(phone_number_list, market.messaging_profile_id)

    # Create pending phone objects for our purchase order.
    status = PhoneNumber.Status.PENDING if client.is_production else PhoneNumber.Status.ACTIVE
    add_numbers(market, status, phone_number_list, client.is_production)

    # Since they come in as pending, after a given interval check that they're active.
    update_pending_numbers.apply_async((market.id,), countdown=5)


def add_numbers(market, status, phones, production):
    """
    Add numbers to PhoneNumber

    :market Market: Instance of a Market the phone belongs to
    :status PhoneNumber.status: status to initiate phone
    :phones list: list of phones to add
    :production bool: Indicate if we're in production
    """
    for phone_number in phones:
        raw_phone = phone_number.replace('+1', '')
        pn_obj = PhoneNumber.objects.create(
            company=market.company,
            market=market,
            status=status,
            phone=raw_phone,
            provider=market.phone_provider,
        )

        if not production:
            # Set a random provider id if in test mode.
            pn_obj.provider_id = uuid.uuid4()
            pn_obj.save()
