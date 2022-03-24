# -*- coding: utf-8 -*-


from django.apps import AppConfig


class CompanyConfig(AppConfig):
    name = 'companies'

    def ready(self):
        import companies.signals  # noqa:F401)
