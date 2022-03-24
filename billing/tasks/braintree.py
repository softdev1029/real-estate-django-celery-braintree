import braintree
from celery import shared_task

from sherpa.models import Company
from ..models import Gateway, Transaction


@shared_task
def sync_braintree_transactions():
    """
    Since we're storing all transactions in sherpa as well as braintree, we need to sync the
    transactions from braintree back into sherpa in case they have become inconsistent.
    """
    company_list = Company.objects.filter(status='active').exclude(braintree_id=None)
    completed = 0

    for company in company_list:
        braintree_id = company.braintree_id
        search_results = Gateway.transaction.search(
            braintree.TransactionSearch.customer_id == braintree_id,
            braintree.TransactionSearch.status == braintree.Transaction.Status.Settled,
        )
        for transaction in search_results.items:
            t, is_new = Transaction.objects.get_or_create(
                transaction_id=transaction.id,
                company=company,
                defaults={'created_with_sync': True},
            )

            if not is_new:
                continue

            if transaction.recurring:
                t.type = Transaction.Type.SUBSCRIPTION
                t.subscription_id = transaction.subscription_id
            else:
                t.type = Transaction.Type.UNKNOWN

            for status_history in transaction.status_history:
                # Loop through status history so that we can get settled and authorized.
                if status_history.status == 'settled':
                    t.is_charged = True
                    t.dt_charged = status_history.timestamp
                    t.amount_charged = status_history.amount
                if status_history.status == 'authorized':
                    t.is_authorized = True
                    t.dt_authorized = status_history.timestamp
                    t.amount_authorized = status_history.amount
            t.save()
        completed += 1
