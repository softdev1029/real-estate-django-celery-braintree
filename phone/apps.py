from django.apps import AppConfig
from django.core.management import call_command
from django.db.models.signals import post_migrate


def populate_phone_tables(sender, **kwargs):
    call_command("loaddata", "carrier")
    call_command("loaddata", "provider")


class PhoneConfig(AppConfig):
    name = 'phone'

    def ready(self):
        post_migrate.connect(populate_phone_tables, sender=self)
