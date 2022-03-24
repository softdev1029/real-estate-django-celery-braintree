from datetime import timedelta

from celery import shared_task

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone as django_tz

from billing.models import Transaction
from core.utils import clean_phone
from phone.choices import Provider
from sherpa.models import Company, Market, PhoneNumber, SMSMessage
from sherpa.tasks import sherpa_send_email
from sms.clients import TelnyxClient
from sms.models import SMSResult
from .utils import process_number_order


@shared_task
def deactivate_company_markets(company_id):
    """
    Deactivate a company's markets and release the phone numbers. Used to fully deactivate a
    company when they've cancelled.
    """
    company = Company.objects.get(id=company_id)
    company_markets = company.market_set.all()

    for market in company_markets:
        market.is_active = False
        market.save(update_fields=['is_active'])
        non_released_numbers = PhoneNumber.objects.filter(
            market=market,
        ).exclude(status=PhoneNumber.Status.RELEASED)

        for phone_number in non_released_numbers:
            phone_number.release()


@shared_task
def release_inactive_phone_numbers():
    """
    Inactive phone numbers from companies without a subscription and haven't sent a message for 7
    days will be released.
    """
    threshold_day = django_tz.now() - timedelta(days=7)

    phone_numbers = PhoneNumber.objects.filter(
        last_send_utc__lt=threshold_day,
        status=PhoneNumber.Status.INACTIVE,
    ).exclude(company__subscription_status__in=[
        Company.SubscriptionStatus.ACTIVE,
        Company.SubscriptionStatus.PAST_DUE,
    ])
    for phone_number in phone_numbers:
        phone_number.release()


@shared_task
def release_company_phone_numbers(phone_number_list, company_id):
    """
    Pass in a list of company phone phone numbers that should be released.

    :phone_number_list Queryset(PhoneNumber): Apparently this accepts a queryset, and can't be an
      actual delayed task, needs to be ran synchronous.
    """
    deleted_count = 0
    for phone_number in phone_number_list:
        phone_number.release()
        deleted_count += 1

    return deleted_count


@shared_task
def purchase_market_numbers(market_id, phone_numbers):
    """
    Purchase a given amount of phone numbers for a market.

    This has much of what's in `purchase_phone_numbers_task` however does not charge the user for
    the extra numbers. Often times this is used in an upgrade that includes the numbers. This task
    is only directly called through django admin, whereas users come through with the one-time
    charge.

    :arg phone_numbers list: List of available phone numbers to purchase.
    :return purchased_count int: Returns the amount of numbers that were purchased. This is useful
                                 downstream to show much should be charged to the user.
    """
    # Gather data needed to purchase the numbers.
    market = Market.objects.get(id=market_id)

    # We will have to change this code when we make this scalable.
    if market.name == 'Twilio':
        return

    company = market.company
    client = company.messaging_client

    # If the market isn't associated with a messaging profile yet, create it and save to market.
    if not market.messaging_profile_id:
        client.create_messaging_profile(market)
        market.refresh_from_db()

    process_number_order(market, phone_numbers)

    return len(phone_numbers)


@shared_task  # noqa: C901
def purchase_phone_numbers_task(market_id, add_quantity, purchase_quantity, user_id,
                                transaction_id=None, best_effort=False):
    """
    Main task to call when adding new phone numbers to a market.

    :param add_quantity int: How many new phone numbers should be added to the market.
    :param purchase_quantity int: How many new phone numbers the user should be charged for. This
                                  can differ because they might not be all overrage.
    :param user_id int: The user id that is purchasing the phone numbers.
    :param transaction_id int: If the user has overrage, they should have an authorized transaction.
    """
    market = Market.objects.get(id=market_id)

    # We will update this when making telephony feature scalable
    if market.name == 'Twilio':
        return

    company = market.company
    User = get_user_model()
    user = User.objects.get(id=user_id)

    # Purchase the phone numbers from provider.
    area_code_1 = market.area_code1
    client = company.messaging_client
    available_response = client.get_available_numbers(
        area_code_1,
        limit=add_quantity,
        best_effort=best_effort,
    )
    available_list = [instance['phone_number'] for instance in available_response['data']]

    # Charge the one-time transaction.
    if transaction_id:
        transaction = Transaction.objects.get(id=transaction_id)
        transaction.charge()
        if not transaction.is_charged:
            return

    purchase_market_numbers(market.id, available_list)

    # Update the company's subscription after the numbers have been purchased.
    company.update_phone_number_addons()

    # Email user when complete.
    sherpa_send_email(
        f'{add_quantity} Sherpa Phone Numbers Added',
        'email/email_phone_numbers_purchased.html',
        user.email,
        {
            'purchased_quantity': purchase_quantity,
            'added_quantity': add_quantity,
            'amount': 1 * purchase_quantity,
            'market': market,
            'first_name': user.first_name,
        },
    )


@shared_task
def update_pending_phone_number(phone_number_id):
    """
    Pass in the phone number instance ID, update its status to active and set its phone number id.
    """
    phone_number_instance = PhoneNumber.objects.get(id=phone_number_id)
    # This is Telnyx specific.
    if phone_number_instance.provider != Provider.TELNYX:
        return

    client = phone_number_instance.client()
    number_response = client.list_numbers(phone_number=phone_number_instance.full_number)
    for phone_data in number_response.json().get('data'):
        phone_number_instance.provider_id = phone_data.get('id')
        phone_number_instance.status = PhoneNumber.Status.ACTIVE
        phone_number_instance.save()

        # Set the connection_id
        payload = {'connection_id': settings.TELNYX_CONNECTION_ID}
        client.update_number(phone_data.get('id'), payload)


@shared_task
def update_delivery_rate():
    """
    Update delivery percentage for each `PhoneNumber` according to telnyx's full history.
    """
    # This is Telnyx specific.
    client = TelnyxClient()
    response = client.messaging_phone_numbers()
    total_pages = response.json().get('meta').get('total_pages')
    page_number = 1

    while True:
        data = response.json().get('data')
        for phone_data in data:
            phone_cleaned = clean_phone(phone_data.get('phone_number'))
            if not phone_cleaned:
                return
            if not PhoneNumber.objects.filter(phone=phone_cleaned).exists():
                continue

            phone_number = PhoneNumber.objects.filter(
                phone=phone_cleaned,
            ).exclude(
                status=PhoneNumber.Status.RELEASED,
            ).first()

            if not phone_number:
                continue

            phone_number.delivery_percentage = phone_data.get('health').get('success_ratio')
            phone_number.save(update_fields=['delivery_percentage'])

        page_number += 1
        if page_number > total_pages:
            break
        response = client.messaging_phone_numbers(page_number=page_number)


@shared_task
def update_sherpa_delivery_rate():
    """
    Update each phone number's bulk send delivery rate while being in the Sherpa system.
    """
    phone_numbers = PhoneNumber.objects.exclude(status=PhoneNumber.Status.RELEASED)
    for phone_number in phone_numbers:
        bulk_messages = SMSMessage.objects.filter(
            from_number=phone_number.full_number,
            campaign__isnull=False,
        )
        results = SMSResult.objects.filter(sms__in=bulk_messages)
        total_count = results.count()
        if total_count < 30 and not settings.TEST_MODE:
            # We only want to show the health when a number has sent enough bulk messages to be
            # representative of its actual health.
            continue

        delivered = results.filter(status=SMSResult.Status.DELIVERED)

        try:
            delivery_rate = round(delivered.count() / total_count, 2)
        except ZeroDivisionError:
            delivery_rate = 0

        phone_number.sherpa_delivery_percentage = delivery_rate
        phone_number.save(update_fields=['sherpa_delivery_percentage'])
