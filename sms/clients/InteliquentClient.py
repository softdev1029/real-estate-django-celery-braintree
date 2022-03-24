import json

import requests

from django.conf import settings

from phone.choices import Provider
from .BaseMessagingClient import BaseMessagingClient


class InteliquentClient(BaseMessagingClient):
    api_url = settings.INTELIQUENT_MICROSERVICE_URL
    provider = Provider.INTELIQUENT

    api_error_msg = "Received unsuccessful status code from inteliquent microservice"

    def get_available_numbers(self, area_code, limit=30):
        body = {
            "area_code": area_code,
            "quantity": limit,
        }
        response = requests.post(f"{self.api_url}/numbers/purchase", json.dumps(body))

        if response.status_code != 200:
            raise ValueError(self.api_error_msg)

        return response.json()

    def get_numbers(self):
        response = requests.get(f"{self.api_url}/numbers")
        if response.status_code != 200:
            raise ValueError(self.api_error_msg)
        return response.json()

    def send_message(self, from_, to, body, media_url=None):
        body = {
            "to_number": to,
            "text": body,
            "media_urls": [media_url] if media_url else [],
        }
        response = requests.post(f"{self.api_url}/numbers/{from_}/send", json.dumps(body))

        if response.status_code != 200:
            raise ValueError(self.api_error_msg)

        return response.json()
