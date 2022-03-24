from core import models
from .btbase import BTBase


class BTPlan(BTBase):
    name = models.CharField(max_length=64)
    description = models.TextField()
    price = models.DecimalField(max_digits=8, decimal_places=2)
    billing_day_of_month = models.PositiveSmallIntegerField(null=True)
    billing_frequency = models.PositiveIntegerField()
    number_of_billing_cycles = models.PositiveIntegerField(null=True)
    trial_period = models.BooleanField()
    trial_duration = models.PositiveIntegerField(null=True)
    trial_duration_unit = models.CharField(max_length=16, null=True)
    discounts = models.ManyToManyField('billing.BTDiscount')
    add_ons = models.ManyToManyField('billing.BTAddon')
