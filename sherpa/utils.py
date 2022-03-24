import base64
import hashlib
import hmac
import io
import operator
import re

import pytz
import unicodecsv as csv

from django.conf import settings
from django.db.models import Count, Max
from django.db.models.functions import Length


def get_field_max_length(model, field_name):
    """
    Return the maximum length for a char field in a given given.

    Used for trimming down database char fields that are too large.
    """
    return model.objects.all() \
        .annotate(text_len=Length(field_name)) \
        .aggregate(Max('text_len')) \
        .get('text_len__max')


def get_model_empty_values(model, check_blank=False):
    """
    Return statistics about a model field's empty or blank values.

    If the field is a CharField we'll also want to see how many instances have a blank value to
    check if it's required or not.
    """
    pass


def get_maximum_distinct_count(model, field_name):
    """
    Return the maximum count of distinct values for a model's field.

    Used to check if a field has duplicate values or if it can be marked as unique.
    """
    return model.objects.values(field_name) \
        .annotate(count=Count(field_name)) \
        .values(field_name) \
        .filter(count__gt=1)


def analyze_model_lengths(model):
    """
    Return a dictionary of charfields with their maximum length as well as their maximum possible
    length, showing which could be trimmed down.
    """
    fields = [f.name for f in model._meta.get_fields()]
    charfields = []

    for field in fields:
        field_type = model._meta.get_field(field).get_internal_type()
        if field_type == 'CharField':
            charfields.append(field)

    data = {}
    for field in charfields:
        possible_max_len = model._meta.get_field(field).max_length
        current_max_length = get_field_max_length(model, field)
        data[field] = {
            'possible_max_len': possible_max_len,
            'current_max_length': current_max_length,
        }

    return data


def get_upload_additional_cost(company, total_rows, upload=None):
    """
    Get estimated additional cost to charge company if their upload exceeds monthly limit.
    """
    cost = 0
    exceeds_count = 0
    if (settings.TEST_MODE or company.subscription) and not company.is_billing_exempt:
        if total_rows > company.upload_count_remaining_current_billing_month:
            exceeds_count = total_rows - company.upload_count_remaining_current_billing_month
            cost_per_upload = company.cost_per_upload
            cost = exceeds_count * cost_per_upload
            if cost < settings.MIN_UPLOAD_CHARGE:
                cost = settings.MIN_UPLOAD_CHARGE

        # UploadProspect has field 'additional_upload_cost_amount', UploadSkipTrace does not.
        if upload and hasattr(upload, 'additional_upload_cost_amount'):
            upload.additional_upload_cost_amount = cost
            upload.save(update_fields=['additional_upload_cost_amount'])

    return cost, exceeds_count


def get_data_from_column_mapping(column_fields, row, obj):
    """
    Get data from a csv row based on column mapping found in given row for given column fields.
    Column fields will have '_column_number' added to get full field name. Name fields include
    'fullname', 'first_name', and last_name'.
    """
    data = {}
    for field in column_fields:
        # Get column number from fields based on Field Mapping (done by user).
        column_number = getattr(obj, f'{field}_column_number')
        if column_number is not None:
            try:
                if field in ['fullname', 'first_name', 'last_name']:
                    row[column_number] = str(row[column_number]).title()
                data[field] = row[column_number]
            except IndexError:
                return None
        else:
            data[field] = ''

    # Make sure first name and last name match full name or create full name if there's none.
    fullname = data.get('fullname', '')
    if fullname != '':
        data['first_name'] = fullname.strip().split(' ')[0]
        data['last_name'] = ' '.join((fullname + ' ').split(' ')[1:]).strip()
    elif data['first_name'] != '' or data['last_name'] != '':
        data['fullname'] = \
            f"{data['first_name']} {data['last_name']}".strip()
    return data


def convert_to_company_local(dt, company):
    """
    Take a datetime object and convert it to be the timezone of the company. If the datetime is
    naive then we have to assume UTC.

    :param datetime dt: datetime object that should be converted
    :param Company company: company instance from which we'll get the timezone to convert to.
    """
    if not dt:
        return None

    is_naive = dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None
    if is_naive:
        dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(pytz.timezone(company.timezone))


def get_average_rate(rate_list):
    """
    Return the average rate, checking to not divide by 0.
    """
    return round(sum(rate_list) / len(rate_list)) if len(rate_list) else 0


def convert_epoch(dt):
    """
    Convert a datetime instance to a ms epoch instance. Mostly used for how freshsuccess is
    expecting dates.
    """
    return round(dt.timestamp() * 1000)


def build_csv(mapper, qs, chunk_size=500):
    """
    Builds a CSV file in memory and returns the bytes.

    :param mapper dict: A dictionary that maps the header to the queryset.
    :param qs QuerySet: The data that will generate the CSV file.
    :param chunk_size int: A number detailing how many instanes of the queryset to pull in each
    batch.
    """
    csv_bytes = io.BytesIO()
    csv_writer = csv.writer(csv_bytes)

    # Write the column headers to the CSV file.
    csv_writer.writerow(list(mapper.keys()))

    for data in qs.iterator(chunk_size=chunk_size):
        row = []
        for key in list(mapper.values()):
            if '.' in key:
                row.append(operator.attrgetter(key)(data))
            else:
                row.append(getattr(data, key))
        csv_writer.writerow(row)
    return csv_bytes.getvalue()


def should_convert_datetime(key):
    """
    Determines if we should attempt to convert a string to a date or datetime in an email task.

    Datetime objects in context are converted to strings when we send to email task, need to turn
    them back into datetime before passing into template for proper template formatting. Only try to
    convert specific fields that have date or datetime beginning or ending their dict key value.

    :return: Boolean determining if we should attempt to convert string to datetime obj.
    """
    checks = [
        '_date' in key,
        '_datetime' in key,
        'date_' in key,
        'datetime_' in key,
    ]

    return any(checks)


def sign_street_view_url(unsigned_url, secret):
    """
    Sign a request URL with a URL signing secret.

    :params unsigned_url str: The unsigned url that is missing the signature
    :params secret str: Signing secret provided by google.
    :return: The fully signed url with signatue.

    [Creating signature](https://developers.google.com/maps/documentation/streetview/get-api-key#dig-sig-manual)  # noqa: E501
    [Useful SO Post](https://stackoverflow.com/questions/56845587/how-to-sign-google-street-view-request-from-python-library)  # noqa: E501
    """
    if not unsigned_url or not secret:
        return None

    decoded_key = base64.urlsafe_b64decode(secret)
    signature = hmac.new(decoded_key, str.encode(unsigned_url), hashlib.sha1)
    decoded_signature = base64.urlsafe_b64encode(signature.digest()).decode()
    return f'https://maps.googleapis.com{unsigned_url}&signature={decoded_signature}'


def has_link(string):
    """
    Pass in a string and check if it has a url link in it.

    :return str: Returns the url or empty string if no url.
    """
    regex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"  # noqa: E501
    url = re.findall(regex, string)
    return url[0][0] if url else ''


def split_ids(string):
    """
    Splits a comma deliminated string into a list of numeric IDs.  Note, will ignore nonnumeric
    characters.

    :param string str: A comma deliminated string of integers.
    :return list: A list of numeric IDs.
    """
    return [int(i) for i in string.split(',') if i.strip().isdigit()]


def get_batch(iterable, step_len):
    """
    Slice iterable based step_len records.

    : param int step_len: step size.
    """
    iter_len = len(iterable)
    for ndx in range(0, iter_len, step_len):
        yield iterable[ndx:min(ndx + step_len, iter_len)]
