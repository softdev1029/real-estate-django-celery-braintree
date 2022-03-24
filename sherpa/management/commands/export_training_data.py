import csv
import datetime

import pytz

from django.core.management.base import BaseCommand
from django.db.models import Case, F, Func, IntegerField, Value, When
from django.db.models.functions import Trim

from campaigns.models import InitialResponse


class Command(BaseCommand):
    """
    Exports a CSV to use in the training of the ML data models.

    Currently, the query will replace all non alpha characters with a space, remove duplicated
    whitespace, and finally trim any excess whitespace.  This should prevent duplicate messages
    such as 'No' being returned.

    There is still one issue that needs to be addressed.  Currently we have no way of knowing if
    the message has been marked incorrectly.  There could be a 'No' marked both 0 and 1 for example.
    """
    def add_arguments(self, parser):
        parser.add_argument('--file', type=str)
        parser.add_argument('--start_date', nargs='?', type=str, default='2015-01-01')

    def handle(self, *args, **options):
        filename = options['file']
        raw_start_date = options['start_date']

        naive_start_date = datetime.datetime.strptime(raw_start_date, "%Y-%m-%d")
        start_date = naive_start_date.astimezone(pytz.utc)

        with open(filename, 'w') as file:
            writer = csv.writer(file)
            count = 0

            rows = InitialResponse.objects.filter(
                campaign__set_auto_dead=True,
                message__prospect__campaignprospect__has_been_viewed=True,
                is_auto_dead=True,
                message__dt__gte=start_date,
            ).annotate(
                cleaned_message=Trim(
                    Func(
                        Func(
                            F('message__message'),
                            Value('[^a-zA-Z]'),
                            Value(' '),
                            Value('g'),
                            function='regexp_replace',
                        ),
                        Value('\s\s+'),  # noqa: W605
                        Value(' '),
                        Value('g'),
                        function='regexp_replace',
                    ),
                ),
                is_dead=Case(
                    When(
                        message__prospect__lead_stage__lead_stage_title__exact='Dead (Auto)',
                        then=Value(1),
                    ),
                    default=Value(0),
                    output_field=IntegerField(),
                ),
            ).values_list('cleaned_message', 'is_dead').distinct('cleaned_message')

            for row in rows.iterator():
                print(row)
                writer.writerow(row)
                count += 1
        return str(count)
