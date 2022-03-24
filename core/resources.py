import csv
import itertools

from import_export import resources
import tablib

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import QuerySet

from companies.models import FileBaseModel


class SherpaResource(resources.Resource):
    """
    Sherpa resource to add additional functionality to the base model.
    """
    def export_field(self, field, obj):
        """
        The original resource does not support querysets that use the `.values()` method.
        This method is used internally and should not be called manually.
        """
        if isinstance(obj, dict):
            return obj.get(field.attribute)
        field_name = self.get_field_name(field)
        method = getattr(self, f'dehydrate_{ field_name }', None)
        if method is not None:
            return method(obj)
        return field.export(obj)

    def iter_queryset(self, queryset, chunk_size=1000):
        if not isinstance(queryset, QuerySet):
            yield from queryset
        elif queryset._prefetch_related_lookups:
            # Django's queryset.iterator ignores prefetch_related which might result
            # in an excessive amount of db calls. Therefore we use pagination
            # as a work-around
            if not queryset.query.order_by:
                # Paginator() throws a warning if there is no sorting
                # attached to the queryset
                queryset = queryset.order_by('pk')
            paginator = Paginator(queryset, chunk_size)
            for index in range(paginator.num_pages):
                yield from paginator.get_page(index + 1)
        else:
            yield from queryset.iterator(chunk_size=chunk_size)


class SherpaModelResource(SherpaResource, metaclass=resources.ModelDeclarativeMetaclass):
    """
    Adds the required funtionality to utilize the `.values()` method.
    """
    def export(self, download_instance, queryset, chunk_size=5000, *args, **kwargs):
        """
        Exports a resource.
        """

        headers = self.get_export_headers()
        data = tablib.Dataset(headers=headers)

        # Sometimes a queryset is passed, other times it is a list of dicts.
        if isinstance(queryset, QuerySet):
            download_instance.total_rows = queryset.count()
        else:
            download_instance.total_rows = len(queryset)


        download_instance.save(update_fields=['total_rows'])

        count = 0
        for obj in super().iter_queryset(queryset, chunk_size=chunk_size):
            data.append(self.export_resource(obj))
            count += 1
            if count % 200:
                download_instance.last_row_processed = count
                download_instance.save(update_fields=['last_row_processed'])

        download_instance.last_row_processed = count
        download_instance.save(update_fields=['last_row_processed'])

        return data

    def batch_import(self, upload_instance, headers=[], batch_size=5000, bulk_create=True,
                     extra_kwargs=None):
        """
        Takes a CSV file found from `upload_instance` or `path` and batch reads the CSV for
        efficient memory usage.

        :param upload_instance Model: An instance of a model based off of `FileBaseModel`.
        :param headers list<String>: A list of strings representing the expected headers in the
        file.
        :param batch_size int: The number of records to read from the file and save to the database.
        :param bulk_create boolean: This will tell the system to use Django's model `.bulk_create`
        method when saving the data to the database.
        :param extra_kwargs dict: A dict of extra values that will be added to each instance when
        created.
        """
        headers = headers or self.get_import_headers()
        start_row = upload_instance.last_row_processed
        path = (upload_instance.file and upload_instance.file.path) or upload_instance.path
        row_count = self.row_count(path)

        upload_instance.total_rows = row_count
        upload_instance.status = FileBaseModel.Status.RUNNING
        upload_instance.save(update_fields=['total_rows', 'status'])

        with open(path, 'r') as f:
            reader = csv.reader(f)
            row_header = next(reader)
            if headers == row_header:
                model = self._meta.model

                while reader.line_num < row_count:
                    instances = []

                    for row in itertools.islice(reader, start_row, batch_size):
                        kwargs = {}

                        for i, field in enumerate(self.get_fields()):
                            kwargs[self.get_field_name(field)] = self.clean_field(field, row[i])

                        if extra_kwargs:
                            kwargs.update(extra_kwargs)

                        instance = model(**kwargs)
                        instances.append(instance)
                    try:
                        with transaction.atomic():
                            # Using a transaction allows us to bulk insert the data and update the
                            # `upload_instance` object without fear of an unexpected failure.
                            if bulk_create:
                                model.objects.bulk_create(instances)
                            else:
                                for instance in instances:
                                    instance.save()

                            upload_instance.last_row_processed = reader.line_num
                            upload_instance.save(update_fields=['last_row_processed'])
                    except Exception:
                        upload_instance.status = FileBaseModel.Status.ERROR
                        upload_instance.save(update_fields=['status'])
                        break
        upload_instance.status = FileBaseModel.Status.COMPLETE
        upload_instance.save(update_fields=['status'])

    def get_import_headers(self):
        return self.get_export_headers()

    def row_count(self, path):
        with open(path, 'r') as f:
            reader = csv.reader(f)
            count = sum(1 for _ in reader)
        return count

    def clean_field(self, field, data):
        field_name = self.get_field_name(field)
        method = getattr(self, f'clean_{ field_name }', None)
        if method is not None:
            return method(data)
        return data
