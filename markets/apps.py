from django.apps import AppConfig


class MarketConfig(AppConfig):
    name = 'markets'

    def ready(self):
        import markets.signals  # noqa:F401
