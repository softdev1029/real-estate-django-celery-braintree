import re

import unicodecsv as csv

from django.http import StreamingHttpResponse


def select_keys(dict_, keys):
    return dict((key, dict_[key]) for key in keys if key in dict_)


def clean_phone(phone_raw):
    """
    Twilio sends us a raw phone number and it should be cleaned through a variety of rules.
    """
    if isinstance(phone_raw, float) or str(phone_raw).count('.') == 1:
        # Can't always see float decimal from excel so this will strip out everything after the 
        # decimal.
        phone_raw = str(phone_raw).split('.')[0]
    # Remove non-number characters
    phone_raw = re.sub(r'\D', "", str(phone_raw))

    # remove "1" from beginning of phone number if added
    if phone_raw[:1] == "1":
        phone_raw = phone_raw[-10:]

    return phone_raw if len(phone_raw) == 10 else ""


def number_display(raw_number):
    """
    Take a raw phone number and return it in display form.
    """
    cleaned_phone = clean_phone(raw_number)
    return "({}) {}-{}".format(
        cleaned_phone[:3],
        cleaned_phone[3:6],
        cleaned_phone[6:],
    )


class CSVResponse(object):
    """
    This class allows you to input a ModelSerializer (from DRF) will output a ready-to-use
    StreamingAPIResponse. Typical usage would be in a custom viewset action or view for CSV
    generation.
    """

    class Echo(object):
        """
        Internal class used to create in-memory CSV files and their HTTP responses.
        """

        def write(self, value):
            return value

    writer = csv.writer(Echo())

    def __init__(self, filename, serializer):
        self.serializer = serializer
        self.filename = filename

    def data(self):
        self.writer.writerow(self.serializer.data[0].keys())
        csv_content = []
        response = StreamingHttpResponse(
            self.generate(),
            content_type="text/csv"
        )
        response['Content-Disposition'] = f'attachment; filename="{self.filename}.csv"'
        return response

    def generate(self):
        yield self.writer.writerow(self.serializer.data[0].keys())
        for row in self.serializer.data:
            yield self.writer.writerow(row.values())
