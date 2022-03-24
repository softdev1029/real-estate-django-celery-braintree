from django.core.management.base import BaseCommand

from markets.tasks import update_pending_numbers
from sherpa.models import PhoneNumber


class Command(BaseCommand):
    """
    With telnyx we place number orders which we need to check on to turn the phone to active.

    Task should be called from cron jobs on production.
    """
    def handle(self, *args, **options):
        pending_market_id_list = PhoneNumber.objects.filter(
            status=PhoneNumber.Status.PENDING,
        ).values_list('market', flat=True).distinct()

        for market_id in pending_market_id_list:
            update_pending_numbers.delay(market_id)
