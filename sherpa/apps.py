from django.apps import AppConfig


class SherpaConfig(AppConfig):
    name = 'sherpa'

    def ready(self):
        import sherpa.signals  # noqa:F401
