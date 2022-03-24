from django.core.management.base import BaseCommand

from search.indexes.stacker import StackerIndex


class Command(BaseCommand):
    """
    Deletes the stacker indexes.
    """
    def handle(self, *args, **options):
        print('Deleting Stacker indexes')
        StackerIndex.delete()
