import braintree

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from phone.tasks import deactivate_company_markets
from sherpa.models import Company
from sherpa.tasks import sherpa_send_email
from .models import Gateway, Transaction

braintree.Configuration.configure(
    settings.BRAINTREE_ENV,
    merchant_id=settings.BRAINTREE_MERCHANT_ID,
    public_key=settings.BRAINTREE_PUBLIC_KEY,
    private_key=settings.BRAINTREE_PRIVATE_KEY,
)


@csrf_exempt  # noqa: C901
def subscription_webhook(request):
    """
    Receive webhook from braintree for all subscription actions.

    https://www.braintreegateway.com/merchants/3sm6qt24mfcgmt34/webhooks/p4r32cdgj9x93rk9/edit
    """
    notice = Gateway.webhook_notification.parse(
        str(request.POST.get('bt_signature')),
        request.POST.get('bt_payload'),
    )
    sub = notice.subscription
    company = Company.objects.filter(subscription_id=sub.id).first()
    subscriptions = Company.SubscriptionStatus
    if not company:
        return HttpResponse(f'Company with subscription id {sub.id} not found.', status=404)

    try:
        transaction_list = sub.transactions

        for transaction in transaction_list:
            t, is_new = Transaction.objects.get_or_create(transaction_id=transaction.id)
            if is_new:
                t.company = company
                if transaction.type == 'credit':
                    t.type = 'sub-refund'
                else:
                    t.type = 'sub-sale'
                t.amount_charged = transaction.amount
                t.is_charged = True
                t.amount_authorized = transaction.amount
                t.is_authorized = True
                if transaction.credit_card:
                    t.last_4 = transaction.credit_card.get('last_4', None)
                t.save()
    except Exception:
        pass

    if notice.kind == braintree.WebhookNotification.Kind.SubscriptionCanceled:
        company.subscription_status = subscriptions.CANCELED
        company.subscription_id = ''
        deactivate_company_markets.delay(company.id)
    elif notice.kind == braintree.WebhookNotification.Kind.SubscriptionChargedSuccessfully:
        if company.subscription_status != subscriptions.PAUSED:
            company.subscription_status = subscriptions.ACTIVE
    elif all([notice.kind == braintree.WebhookNotification.Kind.SubscriptionChargedUnsuccessfully,
              company.subscription_status != subscriptions.PAUSED]):
        company.subscription_status = subscriptions.PAST_DUE
    elif notice.kind == braintree.WebhookNotification.Kind.SubscriptionExpired:
        company.subscription_status = subscriptions.EXPIRED
    elif notice.kind == braintree.WebhookNotification.Kind.SubscriptionTrialEnded:
        company.subscription_status = subscriptions.ACTIVE
    elif notice.kind == braintree.WebhookNotification.Kind.SubscriptionWentActive:
        company.subscription_status = subscriptions.ACTIVE
    elif notice.kind == braintree.WebhookNotification.Kind.SubscriptionWentPastDue:
        if company.subscription_status != subscriptions.PAUSED:
            # We only want to mark the company as past due if they are not currently paused. We
            # still can send them the past due notification, but marking them past due has
            # implications that will activate their market upon reinstatement of their subscription.
            company.subscription_status = subscriptions.PAST_DUE

        # Email the admin that they are past due.
        user = company.admin_profile.user
        sherpa_send_email.delay(
            'Sherpa Subscription Past Due',
            'email/email_subscription_past_due.html',
            user.email,
            {
                'first_name': user.first_name,
                'user_full_name': user.get_full_name(),
                'company_name': company.name,
            },
        )

    company.save()

    return HttpResponse('OK')
