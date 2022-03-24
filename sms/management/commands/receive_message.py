from django.core.management.base import BaseCommand

from sherpa.models import Prospect
from sms.tasks import sms_message_received


class Command(BaseCommand):
    help = 'Imitates receiving a message.'

    def add_arguments(self, parser):
        parser.add_argument('prospect_id', nargs=1, type=int)
        parser.add_argument('message', nargs=1, type=str)

    def handle(self, *args, **options):
        prospect_id = options['prospect_id'][0]
        message = options['message'][0]
        prospect = Prospect.objects.get(id=prospect_id)

        sms_message_received(
            prospect.phone_raw,
            prospect.sherpa_phone_number_obj.phone,
            message,
        )
