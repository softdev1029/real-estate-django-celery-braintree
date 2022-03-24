from decimal import Decimal

from celery import shared_task

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from billing.models import Transaction
from core.utils import clean_phone
from phone.choices import Provider
from phone.utils import process_number_order
from sherpa.models import AreaCodeState, Company, Market, PhoneNumber
from sms.clients import TelnyxClient


@shared_task  # noqa: C901
def purchase_additional_market_task(company_id,
                                    user_email,
                                    area_code,
                                    market_name,
                                    call_forwarding_number,
                                    master_area_code_state_id,
                                    best_effort):
    """
    Assign a new market to a company and handle the asynchronous actions.

    - Charge the company if applicable
    - Purchase market phone numbers
    - Send email to primary user
    """
    company = Company.objects.get(id=company_id)
    call_forwarding_number_clean = clean_phone(call_forwarding_number)
    parent_market = AreaCodeState.objects.get(id=master_area_code_state_id)

    # If the market will be the company's only market, they should not be charged.
    should_charge_market = company.market_set.filter(is_active=True).count() > 1
    if should_charge_market:
        one_time_fee = Decimal(100)
        monthly_fee = Decimal(100)
    else:
        one_time_fee = Decimal(0)
        monthly_fee = Decimal(0)

    subscription = company.subscription
    # TODO: Design a real way to do this
    included_phones = settings.NEW_MARKET_NUMBER_COUNT.DEFAULT
    if Provider.get_by_name(market_name) == Provider.INTELIQUENT and company.is_cedar_crest:
        included_phones = settings.NEW_MARKET_NUMBER_COUNT.INTELIQUENT
    elif subscription and subscription.price >= 1000 and not should_charge_market:
        included_phones = settings.NEW_MARKET_NUMBER_COUNT.EXTRA

    # TODO: Once legacy is gone, the market will always be created in the request view.
    market, _ = Market.objects.update_or_create(
        company=company,
        parent_market=parent_market,
        defaults={
            'name': market_name,
            'area_code1': area_code,
            'area_code2': area_code,
            'call_forwarding_number': call_forwarding_number_clean,
            'is_active': True,
            'one_time_amount': one_time_fee,
            'monthly_amount': monthly_fee,
            'included_phones': included_phones,
        },
    )

    if market.one_time_amount > 0:
        authorize_amount = Decimal(one_time_fee)
        market.one_time_transaction = Transaction.authorize(
            market.company, 'Market Setup Fee', authorize_amount)
        market.save(update_fields=['one_time_transaction'])

    if not market.messaging_profile_id:
        raise Exception(f'Market {market.id} has no messaging profile')

    available_list = list()
    numbers_to_purchase_count = included_phones
    client = market.client
    # TODO: Create a generic interface that works the same despite provider differences
    if market.phone_provider == Provider.TELNYX:
        available_response = client.get_available_numbers(
            market.area_code1,
            limit=numbers_to_purchase_count,
            best_effort=best_effort,
        )
        available_list = [instance.get('phone_number') for instance in available_response['data']]
    elif market.phone_provider == Provider.INTELIQUENT:
        response = client.get_available_numbers(market.area_code1, limit=5)
        available_list = response.get('numbers')

    # Charge One-Time fee if applicable.
    if market.one_time_amount > 0:
        market.charge()
        if not market.one_time_transaction.is_charged:
            market.delete()
            return
    process_number_order(market, available_list)

    # Add $ to monthly subscription if applicable.
    if market.monthly_amount > 0:
        market.create_addon()

    # Send confirmation email.
    if should_charge_market:
        email_address = user_email
        site = Site.objects.get(id=settings.DJOSER_SITE_ID)
        subject = 'Market Added - %s' % market.name
        from_email = settings.DEFAULT_FROM_EMAIL
        to = email_address
        text_content = 'Market Added'
        html_content = render_to_string(
            'email/email_new_market_request_accepted.html', {'market': market, 'site': site})
        email = EmailMultiAlternatives(subject, text_content, from_email, [to])
        email.attach_alternative(html_content, "text/html")
        email.send()


@shared_task
def update_pending_numbers(market_id):
    """
    With telnyx we place number orders which get fulfilled, this task will look to see which of
    our pending numbers are now active.
    """
    market = Market.objects.get(id=market_id)
    # This is Telnyx specific. Likely this Twilio check will change when we make this more scalable.
    if market.name == 'Twilio':
        return

    client = TelnyxClient()
    pending_numbers = PhoneNumber.objects.filter(status=PhoneNumber.Status.PENDING, market=market)
    numbers_response = client.list_numbers(messaging_profile_id=market.messaging_profile_id)

    if numbers_response.status_code != 200:
        # There is currently a problem with the telnyx numbers API
        return

    response_data = numbers_response.json().get('data')
    # Build up a dictionary of the data that we need later.
    number_data = {}
    for d in response_data:
        number_data[d.get('phone_number')] = (d.get('id'), d.get('status'))

    # Loop through the pending numbers and update active if it's marked as active.
    for phone_number in pending_numbers:
        number = phone_number.full_number
        number_record = number_data.get(number)

        # Run the logic when the phone number should be made active.
        if number_record and number_record[1] == 'active':
            phone_number.status = PhoneNumber.Status.ACTIVE
            phone_number.provider_id = number_record[0]
            phone_number.save(update_fields=['status', 'provider_id'])

            # Set the connection_id
            payload = {'connection_id': settings.TELNYX_CONNECTION_ID}
            client.update_number(number_record[0], payload)


@shared_task
def update_numbers(market_id, payload):
    """
    Update numbers in telnyx with a given payload.

    :market_id: Id of the market instance to have its numbers updated.
    :payload: Dictionary of data to send in the telnyx api request.
    """
    market = Market.objects.get(id=market_id)
    market.update_numbers(payload)
