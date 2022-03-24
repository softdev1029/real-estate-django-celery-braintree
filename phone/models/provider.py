from core import models
from .carrier import Carrier


class Provider(models.Model):
    """
    Centralized settings and way to access phone providers.
    """
    TWILIO = 'twilio'
    TELNYX = 'telnyx'
    INTELIQUENT = 'inteliquent'

    CHOICES = (
        (TWILIO, 'Twilio'),
        (TELNYX, 'Telnyx'),
        (INTELIQUENT, 'Inteliquent'),
    )

    id = models.CharField(primary_key=True, choices=CHOICES, max_length=50)
    priority = models.PositiveIntegerField(unique=True)
    managed = models.BooleanField()
    sms_market_minimum = models.PositiveIntegerField()
    new_market_number_count = models.PositiveIntegerField()
    messages_per_phone_per_day = models.PositiveIntegerField()
    opt_out_language = models.TextField()
    excluded_carriers = models.ManyToManyField(Carrier, blank=True)

    def __str__(self):
        return self.get_id_display()
