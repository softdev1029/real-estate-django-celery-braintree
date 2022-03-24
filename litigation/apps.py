# -*- coding: utf-8 -*-


from django.apps import AppConfig


class LitigationConfig(AppConfig):
    name = 'litigation'

    def ready(self):
        import litigation.signals  # noqa:F401
