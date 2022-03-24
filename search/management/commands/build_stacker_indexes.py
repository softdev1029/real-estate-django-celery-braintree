from django.core.management.base import BaseCommand

from search.indexes.stacker import StackerIndex


class Command(BaseCommand):
    """
    Builds the stacker indexes.
    """
    def handle(self, *args, **options):
        print('Creating Stacker indexes')
        StackerIndex.create()
