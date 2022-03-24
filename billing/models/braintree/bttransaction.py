from core import models
from .btbase import BTBase


class BTTransaction(BTBase):
    customer_id = models.CharField(max_length=64)
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    refunded_transaction_id = models.CharField(max_length=64, null=True)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    custom_type = models.CharField(max_length=32, null=True)
    gateway_rejection_reason = models.CharField(max_length=32, null=True)
    plan_id = models.CharField(max_length=32, null=True)
    recurring = models.BooleanField(default=False)
    t_type = models.CharField(max_length=32, null=True)
    discount_amount = models.DecimalField(max_digits=8, decimal_places=2)
    status = models.CharField(max_length=32)

    # Billing Detail
    first_name = models.CharField(max_length=64, null=True)
    last_name = models.CharField(max_length=64, null=True)
    street_address = models.CharField(max_length=128, null=True)
    postal_code = models.CharField(max_length=5)

    # CC Detail
    last_4 = models.SmallIntegerField()


class BTTransactionStatus(models.Model):
    transaction_id = models.ForeignKey(BTTransaction, on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    timestamp = models.DateTimeField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    source = models.CharField(max_length=32, null=True)
