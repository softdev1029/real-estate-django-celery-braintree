from core import models
from .btbase import BTBase


class BTModifier(BTBase):
    name = models.CharField(max_length=64)
    description = models.TextField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    never_expires = models.BooleanField()
    number_of_billing_cycles = models.PositiveIntegerField(null=True)

    class Meta:
        abstract = True


class BTAddon(BTModifier):
    pass


class BTDiscount(BTModifier):
    pass
