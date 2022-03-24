from django.conf import settings
from django.core.management.base import BaseCommand

from sherpa.models import Market
from sms.clients import TelnyxClient


class Command(BaseCommand):
    """
    Setup the messaging profiles for george and relay dev to send their webhooks to the ngrok url.
    """
    def add_arguments(self, parser):
        parser.add_argument('ngrok_url', type=str)

    def handle(self, *args, **options):
        ngrok_url = options['ngrok_url']
        market = Market.objects.get(id=settings.DJOSER_SITE_ID)
        profiles = [settings.TELNYX_RELAY_MESSAGING_PROFILE_ID, market.messaging_profile_id]

        for messaging_profile_id in profiles:
            client = TelnyxClient(is_production=True)
            webhook_url = f'{ngrok_url}/api/v1/sms-messages/received_telnyx/'
            client.update_messaging_profile(messaging_profile_id, webhook_url=webhook_url)
