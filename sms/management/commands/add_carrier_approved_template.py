from django.core.management.base import BaseCommand
from django.utils import timezone

from sms.models import CarrierApprovedTemplate


class Command(BaseCommand):
    """

    """
    help = 'Adds the carrier-approved templates into the system.'

    def add_arguments(self, parser):
        parser.add_argument('message', type=str)

    def handle(self, *args, **options):
        message = options['message']
        CarrierApprovedTemplate.objects.create(
            message=message,
            is_verified=True,
            is_active=True,
            verified=timezone.now(),
        )
