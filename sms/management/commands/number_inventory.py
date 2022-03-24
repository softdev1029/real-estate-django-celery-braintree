import csv

import telnyx

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Builds a CSV file of our Telnyx number inventory.
    """

    def add_arguments(self, parser):
        parser.add_argument('filename', type=str)

    def handle(self, *args, **options):
        telnyx.api_key = settings.TELNYX_SECRET_KEY
        telnyx.max_network_retries = 3

        filename = options['filename']
        current_page = 1
        inventory = []

        while True:
            numbers = telnyx.PhoneNumber.list(page={"number": current_page, "size": 1000})
            current_page += 1
            inventory.extend([{
                "id": number["id"],
                "connection_id": number["connection_id"],
                "status": number["status"],
                "phone_number": number["phone_number"],
                "messaging_profile_id": number["messaging_profile_id"],
                "messaging_profile_name": number["messaging_profile_name"],
            } for number in numbers])
            print(f"{len(inventory)} of {numbers['meta']['total_results']} numbers.")
            if len(inventory) >= numbers["meta"]["total_results"]:
                break

        with open(filename, 'w') as f:
            w = csv.DictWriter(f, fieldnames=list(inventory[0].keys()))
            w.writeheader()
            w.writerows(inventory)
