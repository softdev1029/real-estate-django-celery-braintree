from django.contrib.postgres.fields import ArrayField

from core import models


class Carrier(models.Model):
    """
    Centrailized source for any phone carrier data needed
    """
    ATT = 'att'
    T_MOBILE = 't-mobile'
    VERIZON = 'verizon'

    CHOICES = (
        (ATT, 'AT&T'),
        (T_MOBILE, 'T-Mobile'),
        (VERIZON, 'Verizon'),
    )

    id = models.CharField(primary_key=True, choices=CHOICES, max_length=50)
    carrier_keys = ArrayField(
        models.CharField(max_length=50),
        help_text="Possible values returned when fetching carrier data (comma separated)",
        db_index=True,
    )

    def __str__(self):
        return self.get_id_display()
