from datetime import datetime, timedelta
from functools import lru_cache

import braintree
from celery import shared_task
from celery.utils.log import get_task_logger

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from sherpa.models import Company, UserProfile
from ..integrations.braintree import gateway
from ..integrations.salesforce import get_salesforce_client

User = get_user_model()
logger = get_task_logger(__name__)


@lru_cache(maxsize=None)
def get_allowed_companies():
    return Company.objects.filter(
        braintree_id__isnull=False).prefetch_related('cancellation_requests')


@lru_cache(maxsize=None)
def get_companies_indexed_by_btid():
    return {
        c.braintree_id: c for c in get_allowed_companies()
    }


accounts_pushed = set()


@lru_cache(maxsize=None)
def update_or_create_account_and_contacts(salesforce, company, bt_subscription=None):
    """ Update or create a Salesforce Account and related Contacts given a Braintree ID.
    Return a set of invalid email addresses for any Contacts not made, or None if the Company does
    not exist.
    """
    salesforce.upsert_account_from_company(company, bt_subscription)
    invalid_email_addresses = set()
    for userprofile in UserProfile.objects.valid().filter(company_id=company.pk).select_related(
            'user').prefetch_related('interesting_features'):
        # TODO: enforce email validation and remove
        try:
            validate_email(userprofile.user.email)
        except ValidationError:
            invalid_email_addresses |= {userprofile.pk}
            continue
        salesforce.upsert_contact_from_userprofile(userprofile)
    return invalid_email_addresses


@shared_task(bind=True)
def full_sync_to_salesforce(self, lookback=2, offset=0):
    """ Using Braintree and the database, assemble the data required to push to Salesforce.

    Braintree's data integrity is largely centered around recurring transactions.  Such
    transactions assume users have entered Plan details (base amount, frequency, terms, etc.),
    Add-ons, and Discounts.  Once those are entered, a Subscription can be attached to a
    Customer, and than a Transaction will be charged tied to the Subscription.  Additionally,
    one-off transactions can be entered, but Braintree is generally not in the business of
    caring what those transactions are.
    """

    # status output for early exit
    salesforce = get_salesforce_client()
    logger.info(f'Pushing data to {salesforce.sf_instance}')

    # groom local items first
    get_companies_indexed_by_btid()

    # review braintree-controlled items
    gateway.get_allowed_plans()
    gateway.get_allowed_add_ons()
    gateway.get_allowed_discounts()

    # Get all settled Transactions since the cutoff date
    start_date = datetime.today().date() - timedelta(days=lookback + offset)

    invalid_email_addresses = set()
    missing_companies = set()
    invalid_subscriptions = set()
    invalid_products = set()
    companies_subscribed = set()
    companies_active = set()

    def sync_transactions_to_salesforce(day, source):

        # get the transactions for the day and source
        transactions = gateway.get_settled_transactions_for_date(
            day,
            braintree.TransactionSearch.source == source,
            braintree.TransactionSearch.status == braintree.Transaction.Status.Settled,
        )
        print(f'Processing {len(transactions.ids)} {source} transactions for '
              f'{day}', end='', flush=True)
        for (Nt, transaction) in enumerate(transactions, start=1):
            print('.' if Nt % 10 else Nt, end='', flush=True)

            # need to make sure the account exists and is upserted first
            company = get_companies_indexed_by_btid().get(transaction.customer['id'])
            if not company:
                missing_companies.add(transaction.id)
                continue

            bt_subscription = gateway.get_subscription(transaction.subscription_id)

            # skip disallowed subscriptions
            if transaction.subscription_id and not bt_subscription:
                invalid_subscriptions.add(transaction.id)
                continue

            # upsert account and contacts
            invalid_email_addresses.update(
                update_or_create_account_and_contacts(salesforce, company, bt_subscription))

            # now create the opportunity and related line items
            invalid_products.update(salesforce.upsert_opportunity_from_transaction(
                transaction, company.pk, bt_subscription,
            ))

            companies_active.add(company.id)
            if bt_subscription:
                companies_subscribed.add(company.id)
        print()

    # process each day in the window
    for dayN in range(lookback):
        # process recurring first since that will amend subscription data to the account
        for source in (
            braintree.Transaction.Source.Recurring,
            braintree.Transaction.Source.Api,
            braintree.Transaction.Source.ControlPanel,
        ):
            sync_transactions_to_salesforce(start_date + timedelta(days=dayN), source)

    logger.info(f'Transactions skipped for invalid email addresses: {len(invalid_email_addresses)}')
    logger.info(f'Transactions skipped for missing companies: {len(missing_companies)}')
    logger.info(f'Transactions skipped for invalid subscriptions: {len(invalid_subscriptions)}')
    logger.info(f'Transactions skipped for invalid products: {len(invalid_products)}')
    logger.info(f'Accounts subscribed/active/total: '
                f'{len(companies_subscribed)}/'
                f'{len(companies_active)}/'
                f'{Company.objects.count()}')
