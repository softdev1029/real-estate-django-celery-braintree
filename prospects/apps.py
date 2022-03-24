# -*- coding: utf-8 -*-


from django.apps import AppConfig


class ProspectsConfig(AppConfig):
    name = 'prospects'

    def ready(self):
        import prospects.signals  # noqa:F401
