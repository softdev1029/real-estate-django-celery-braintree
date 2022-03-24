from django.conf import settings
from django.utils import timezone as django_tz

from core import models
from .product import Product
from ..integrations.braintree import Gateway


class Transaction(models.Model):

    Type = Product.SKU

    dt_created = models.DateTimeField(default=django_tz.now)
    type = models.CharField(null=True, blank=True, max_length=16, choices=Type.CHOICES)
    last_4 = models.CharField(null=True, blank=True, max_length=5)
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    description = models.TextField(null=True, blank=True)
    transaction_id = models.CharField(max_length=255, null=True, blank=True)
    amount_authorized = models.DecimalField(null=True, blank=True, max_digits=8, decimal_places=2)
    dt_authorized = models.DateTimeField(null=True, blank=True)
    is_authorized = models.BooleanField(default=False)
    amount_charged = models.DecimalField(null=True, blank=True, max_digits=8, decimal_places=2)
    dt_charged = models.DateTimeField(null=True, blank=True)
    is_charged = models.BooleanField(default=False)
    is_failed = models.BooleanField(default=False)
    failure_reason = models.TextField(null=True, blank=True)
    created_with_sync = models.BooleanField(default=False)

    def charge(self, amount=None):
        """
        Charge a previously authorized transaction.

        :param amount: can be None or a value. If `amount` is None, then it will charge the amount
            authorized, unless a charge amount has been added.
        :return: Boolean if the charge was successful.
        """
        if not self.is_authorized:
            raise Exception('This transaction has not been authorized.')
        if self.is_failed:
            raise Exception('This transaction has not been declined and cannot be processed.')
        if self.is_charged:
            raise Exception('This transaction has already been charged.')
        if not self.transaction_id:
            raise Exception('No transaction id.')

        if not amount:
            if self.amount_charged:
                amount = self.amount_charged
            else:
                amount = self.amount_authorized
        if amount > self.amount_authorized:
            amount = self.amount_authorized
        self.dt_charged = django_tz.now()
        self.amount_charged = amount
        result = Gateway.transaction.submit_for_settlement(
            self.transaction_id,
            amount='%.2f' % amount,
        )
        if result.is_success:
            self.is_charged = True
            self.save()
            return True
        else:
            self.is_failed = True
            self.failure_reason = result.message
            for error in result.errors.deep_errors:
                self.failure_reason += f'\n\n{error.attribute}\n{error.code}\n{error.message}'
            self.save()
            return False

    @staticmethod  # noqa: C901
    def authorize(company, description, amount):
        """
        Authorize a new transaction. Check `transaction.is_failed` to see if it
        succeeded or not.

        returns `transaction`
        """

        if amount < 0:
            raise Exception('Can\'t authorize a negative amount.')

        # TODO: (awwester) We should be passing in type instead and then giving the description.
        if description == 'Sherpa Skip Trace Fee':
            transaction_type = Transaction.Type.SKIP_TRACE
        elif description == 'Sherpa Upload Fee':
            transaction_type = Transaction.Type.UPLOAD
        elif 'Sherpa Credits - ' in description:
            transaction_type = Transaction.Type.SHERPA_CREDITS
        elif description == 'Market Setup Fee':
            transaction_type = Transaction.Type.MARKET
        elif description == 'Additional Phone Numbers':
            transaction_type = Transaction.Type.PHONE_PURCHASE
        elif description == 'Annual Subscription':
            transaction_type = Transaction.Type.SUBSCRIPTION
        elif description == 'Direct mail fee':
            transaction_type = Transaction.Type.DIRECT_MAIL
        else:
            transaction_type = Transaction.Type.UNKNOWN

        transaction = Transaction(
            company=company,
            description=description,
            amount_authorized=amount,
            dt_authorized=django_tz.now(),
            type=transaction_type,
        )
        transaction.save()

        if settings.TEST_MODE:
            return transaction

        result = Gateway.transaction.sale({
            'customer_id': transaction.company.braintree_id,
            'amount': '%.2f' % transaction.amount_authorized,
            'custom_fields': {
                'type': transaction_type,
            },
        })

        if result.is_success:
            transaction.is_authorized = True
            transaction.transaction_id = result.transaction.id
        else:
            transaction.is_failed = True
            transaction.failure_reason = result.message
            for error in result.errors.deep_errors:
                transaction.failure_reason += (f'\n\n{error.attribute}\n'
                                               f'{error.code}\n'
                                               f'{error.message}')

        transaction.save()
        return transaction
