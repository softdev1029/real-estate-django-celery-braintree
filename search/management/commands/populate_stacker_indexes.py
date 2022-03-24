from django.core.management.base import BaseCommand

from search.tasks import populate_by_company_id
from sherpa.models import Company


class Command(BaseCommand):
    """
    Builds the stacker indexes.
    """
    def handle(self, *args, **options):
        print("Populating Stacker indexes")
        comp_ids = list(Company.objects.filter(
            subscription_status=Company.SubscriptionStatus.ACTIVE,
        ).values_list('id', flat=True))
        print(f"Loading {len(comp_ids)} companies")
        populate_by_company_id.delay(comp_ids)
