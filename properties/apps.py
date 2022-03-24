from django.apps import AppConfig


class PropertiesConfig(AppConfig):
    name = 'properties'

    def ready(self):
        import properties.signals  # noqa: F401
