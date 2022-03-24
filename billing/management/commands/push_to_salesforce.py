from django.core.management.base import BaseCommand

from ...tasks.salesforce import full_sync_to_salesforce


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--delay', action='store_true', default=False,
                            help='Set to place on a deferred task.')
        parser.add_argument('--lookback', type=int, default=2,
                            help='Lookback in days, minimum is 1, default is 2.')
        parser.add_argument('--offset', type=int, default=0,
                            help='Offset starting point by N days, default is today.')

    def handle(self, *args, **options):
        delay = options['delay']
        lookback = options['lookback']
        assert lookback > 0
        offset = options['offset']
        kwargs = dict(lookback=lookback, offset=offset)
        func = full_sync_to_salesforce
        if delay:
            func = func.delay
        func(**kwargs)
