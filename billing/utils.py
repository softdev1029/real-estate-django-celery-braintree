from billing.exceptions import SubscriptionException
from billing.models import product


def map_braintree_status(raw_status):
    """
    Take in the raw status from braintree and map it to a display value for sherpa users.
    """
    failed_statuses = [
        'processor_declined',
        'gateway_rejected',
        'voided',
        'settlement_declined',
        'failed',
    ]

    if raw_status in failed_statuses:
        return 'Failed'
    elif raw_status == 'settled':
        return 'Paid'
    elif raw_status == 'authorized':
        return 'Authorized'

    return 'Pending'


def calculate_annual_price(plan_id):
    """
    Calculates the annual price.  This should be a value from the Plan model.
    """
    if plan_id == product.SMS_PRO:
        return 900 * 12
    elif plan_id == product.SMS_CORE:
        return 450 * 12
    else:
        raise SubscriptionException(
            f'Could not process annual subscription for plan {plan_id}')


DISCOUNT_TWILIO_STARTER = 'twilio-starter-50'
DISCOUNT_TWILIO_CORE = 'twilio-core-100'
DISCOUNT_TWILIO_PRO = 'twilio-pro-200'
DISCOUNT_TWILIO_ENTERPRISE = 'twilio-enterprise-200'

twilio_discount_mapping = {
    product.SMS_STARTER: DISCOUNT_TWILIO_STARTER,
    product.SMS_CORE: DISCOUNT_TWILIO_CORE,
    product.SMS_PRO: DISCOUNT_TWILIO_PRO,
    product.SMS_ENTERPRISE: DISCOUNT_TWILIO_ENTERPRISE,
}


def get_twilio_discount_id(plan_id):
    """
    Returns the discount id for twilio based on the plan_id.
    """
    try:
        return twilio_discount_mapping[plan_id]
    except KeyError:
        raise SubscriptionException(
            f'Could not process twilio discount id for plan {plan_id}')


upload_limit_mapping = {
    product.SMS_STARTER: 5000,
    product.SMS_CORE: 10000,
    product.SMS_PRO: 25000,
    product.SMS_ENTERPRISE: 25000,
}

upload_limit_mapping_twilio = {
    product.SMS_STARTER: 5000,
    product.SMS_CORE: 15000,
    product.SMS_PRO: 35000,
    product.SMS_ENTERPRISE: 999999,
}


def get_upload_limit_by_plan_id(plan_id, with_twilio=False):
    """
    Returns the upload limits based on plan_id.
    """
    mapping = upload_limit_mapping_twilio if with_twilio else upload_limit_mapping
    try:
        return mapping[plan_id]
    except KeyError:
        raise SubscriptionException(
            f'Could not process monthly upload limit for plan {plan_id}')
