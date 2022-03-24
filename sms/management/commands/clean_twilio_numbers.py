from django.core.management.base import BaseCommand
from django.db.models import Q

from phone.tasks import release_company_phone_numbers
from sherpa.models import Company, PhoneNumber


class Command(BaseCommand):
    """
    Sometimes we have phone numbers in our account that should not be there. This command releases
    all of those numbers that we should not be paying for anymore.
    """
    help = 'Release active phone numbers from non-subscription accounts.'

    def handle(self, *args, **options):
        inactive = Company.objects.exclude(status=Company.Status.ACTIVE)
        without_subscription = Company.objects.filter(
            ~Q(name='Cedar Crest Properties'),
            Q(subscription_id="") | Q(subscription_id=None),
            status=Company.Status.ACTIVE,
        )
        qs_list = [inactive, without_subscription]

        for queryset in qs_list:
            for company in queryset:
                numbers = company.phone_numbers.exclude(status=PhoneNumber.Status.RELEASED)
                if numbers:
                    release_company_phone_numbers(numbers, company.id)
