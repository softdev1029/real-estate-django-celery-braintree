from collections import Counter
from io import StringIO
import json
import traceback
import uuid

import chardet
from requests.exceptions import ChunkedEncodingError, ConnectionError
from unicodecsv import csv

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import F
from django.utils import timezone as django_tz

from skiptrace.models import UploadSkipTrace
from .models import Prospect, UploadLitigatorCheck, UploadProspects
from .utils import get_batch, get_upload_additional_cost


class DeDuplicationInterFace:
    """
    Interface for eradicating duplicates based on the previous
    existing Prospect
    """
    def __init__(self):
        self.data = []
        self.total_rows = 0
        self.duplicated_count = 0

    def map_upload_prospect(self, is_prospect_ids_required=False):  # noqa: C901
        """
        overriding existing method to prevent duplication for DM campaign
        """
        mailing_street_key_count = Counter(x.get('mailing_street') for x in self.data)
        property_street_key_count = Counter(x.get('street') for x in self.data)
        unique_values = []
        duplicate_values = []
        for an_obj in self.data:
            # Remove extra numbers since we only want one Prospect with one address.
            if 'phone_2_number' in an_obj:
                del an_obj['phone_2_number']
            if 'phone_3_number' in an_obj:
                del an_obj['phone_3_number']

            unique = mailing_street_key_count[an_obj.get('mailing_street')] == 1
            if not an_obj.get('mailing_street'):
                unique = property_street_key_count[an_obj.get('street')] == 1

            if unique:
                unique_values.append(an_obj)
            else:
                duplicate_values.append(an_obj)

        pros = Prospect.objects.filter(
            prop__mailing_address__address__in=[x.get('mailing_street') for x in duplicate_values],
            prop__address__address__in=[x.get('street') for x in duplicate_values],
        )

        update_keys = [
            'first_name',
            'last_name',
            'street',
            'city',
            'state',
            'zipcode',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zipcode',
        ]
        already_added = set()
        prospects_ids = [x.get('id') for x in unique_values]
        for an_duplicated in duplicate_values:
            to_check_val = an_duplicated.get('mailing_street')
            use_property_address = False
            if not to_check_val:
                to_check_val = an_duplicated.get('street')
                use_property_address = True
            if to_check_val not in already_added:
                prefix = 'mailing' if not use_property_address else 'property'
                obj_qs = pros.filter(**{f'{prefix}_address': to_check_val})
                data = {}
                if obj_qs.exists():
                    if_owner_verify = \
                        obj_qs.filter(owner_verified_status=Prospect.OwnerVerifiedStatus.VERIFIED)

                    if if_owner_verify.exists():
                        if if_owner_verify.count() == 1:
                            an_pros = if_owner_verify[0]
                        else:
                            if_owner_verify = if_owner_verify.order_by('-created_date')
                            an_pros = if_owner_verify[0]
                    else:
                        latest_qs = obj_qs.order_by('-created_date')
                        an_pros = latest_qs[0]

                    for key in an_duplicated.keys():
                        field = key if 'zipcode' not in key else key.replace('code', '')
                        field = field if 'street' not in field else field.replace(
                            'street',
                            'address',
                        )
                        if field != 'first_name' and field != 'last_name':
                            field = field if 'mailing' in field else f'property_{field}'

                        data[key] = an_duplicated[key] if key not in update_keys else getattr(
                            an_pros,
                            field,
                        )
                    if an_pros.id not in prospects_ids:
                        prospects_ids.append(an_pros.id)

                already_added.add(to_check_val)
                unique_values.extend([data if data else an_duplicated])
                duplicate_values.remove(an_duplicated)

        self.data = unique_values
        self.total_rows = len(unique_values)
        self.duplicated_count = len(duplicate_values)

        if is_prospect_ids_required:
            return prospects_ids, True
        return prospects_ids, False


class CSVFieldMapper(DeDuplicationInterFace):
    """
    Map fields from a CSV file uploaded from Flatfile
    """
    def __init__(self, request, upload_object_id=None):
        """
        'user' is the `User` that uploaded the CSV.
        'data' holds'validData' in request. This is the data that passed field validation.
        'headers' is 'headersMatched' from request. These are the headers Flatfile matched.
        'filename' is the original file name from request.
        'total_rows' is the number of records validated in Flatfile.
        'upload_object' is the object to save field mapping data to.
        'column_names' is a list of column names to map.
        'path' is a unique name to save CSV to.
        """
        super().__init__()
        self.user = request.user
        self.data = json.loads(request.data.get('valid_data', '[]'))
        self.headers = json.loads(request.data.get('headers_matched', '[]'))
        self.filename = request.data.get('uploaded_filename', '').replace('%20', ' ')
        self.total_rows = len(self.data)
        self.upload_object = None
        self.upload_object_id = upload_object_id
        self.column_names = []
        self.success = False
        self.additional_cost = 0
        self.exceeds_count = 0
        self.duplicated_count = 0

    def request_valid(self):
        """
        Check if data sent in request is valid.
        """
        headers_schema = ['matched_key', 'letter']
        if not (self.filename and self.data and self.headers):
            return False

        for key in headers_schema:
            if key not in self.headers[0]:
                return False

        key = self.headers[0]['matched_key']
        if key not in self.data[0]:
            return False

        return True

    def map_upload_skip_trace(self):
        """
        Save a CSV file and map it's fields for an `UploadSkipTrace` object.
        """
        if not self.request_valid():
            return None

        self.column_names = [
            'fullname',
            'first_name',
            'last_name',
            'property_street',
            'property_city',
            'property_state',
            'property_zipcode',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zipcode',
            'custom_1',
            'custom_2',
            'custom_3',
            'custom_4',
            'custom_5',
            'custom_6',
        ]
        self.upload_object = UploadSkipTrace.create_new(
            self.user,
            self.total_rows,
            self.filename,
        )

        if self.save_file():
            self.success = self.map_fields()

    def map_upload_prospect(
            self, campaign=None, confirm_additional_cost=False, campaign_type="sms",
    ):
        """
        Save a CSV file and map it's fields for an `UploadSkipTrace` object.

        :return: Returns the `UploadProspect` instance.
        """
        if not self.request_valid():
            return None

        self.column_names = [
            'fullname',
            'first_name',
            'last_name',
            'street',
            'city',
            'state',
            'zipcode',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zipcode',
            'email',
            'custom_1',
            'custom_2',
            'custom_3',
            'custom_4',
            'phone_1_number',
            'phone_2_number',
            'phone_3_number',
        ]

        if campaign_type.lower() == "dm" or (campaign and campaign.is_direct_mail):
            super().map_upload_prospect()

        self.upload_object = UploadProspects.create_new(
            self.user,
            self.total_rows,
            self.filename,
            campaign,
            duplicated_prospects=self.duplicated_count,
        ) if not self.upload_object_id else UploadProspects.objects.get(
            id=int(self.upload_object_id))

        # We only want to check for additional charge if pushing to campaign.
        if campaign:
            self.additional_cost, self.exceeds_count = \
                get_upload_additional_cost(campaign.company, self.total_rows, self.upload_object)

        if self.exceeds_count:
            self.upload_object.exceeds_count = self.exceeds_count
            self.upload_object.save(update_fields=['exceeds_count'])

        if (confirm_additional_cost or not self.exceeds_count) and self.save_file():
            self.success = self.map_fields(
                no_suffix=['phone_1_number', 'phone_2_number', 'phone_3_number'])

        return self.upload_object

    def map_upload_litigator_check(self):
        """
        Save a CSV file and map it's fields for an `UploadSkipTrace` object.
        """
        if not self.request_valid():
            return None

        self.column_names = [
            'fullname',
            'first_name',
            'last_name',
            'street',
            'city',
            'state',
            'zipcode',
            'mailing_street',
            'mailing_city',
            'mailing_state',
            'mailing_zipcode',
            'email',
            'custom_1',
            'custom_2',
            'custom_3',
            'phone_1_number',
            'phone_2_number',
            'phone_3_number',
        ]

        check_litigator_hash = uuid.uuid4()

        self.upload_object = UploadLitigatorCheck.objects.create(
            path=f'{check_litigator_hash}.xls',
            token=check_litigator_hash,
            uploaded_filename=self.filename,
            total_rows=self.total_rows,
        )

        if self.save_file():
            self.success = self.map_fields(
                no_suffix=['phone_1_number', 'phone_2_number', 'phone_3_number'])

    def save_file(self):
        """
        Save CSV to file.
        """
        if not self.upload_object:
            return False

        buffer = StringIO()
        fd_writer = csv.writer(buffer, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        fd_writer.writerow([header['letter'] for header in self.headers])
        for s in self.data:
            fd_writer.writerow([val for val in s.values()])

        self.upload_object.file.save(self.filename, ContentFile(buffer.getvalue().encode('utf-8')))

        # Update path from the file so that everything works as intended.
        self.upload_object.path = self.upload_object.file.name
        self.upload_object.save()
        return True

    def map_fields(self, no_suffix=None):
        """
        Given a set of column names in 'column_names', map fields to upload_object.

        no_suffix is a list of fields that don't have 'column_number' appended to the field name.
        """
        if not self.upload_object or not self.column_names:
            return False

        update_fields = []
        for field in self.column_names:
            update_field = f"{field}_column_number"
            if no_suffix and field in no_suffix:
                update_field = field
            setattr(self.upload_object, update_field, None)
            update_fields.append(update_field)

        header_names = [header['matched_key'] for header in self.headers]
        for index, column_mapping in enumerate(header_names):
            suffix = '_column_number'
            if no_suffix and column_mapping in no_suffix:
                suffix = ''
            setattr(self.upload_object, f"{column_mapping}{suffix}", index)

        self.upload_object.save(update_fields=update_fields)
        return True


class ProcessUpload:
    """
    Save data from an uploaded CSV file.
    """
    success = False
    cancelled = False
    STOP = 'stop'
    SKIP = 'skip'
    CONTINUE = 'continue'

    def __init__(self, upload, upload_type, is_batch=False):
        """
        :param upload: An upload object (ex: UploadSkipTrace, UploadProspects)
        :param upload_type: String with type of upload: 'skip_trace', 'prospects'
        """
        self.upload = upload
        self.processed_header = False
        self.upload_type = upload_type
        self.upload_model = UploadSkipTrace if upload_type == 'skip_trace' else UploadProspects
        self.demo_limit = 50
        self.batch_limit = settings.UPLOAD_PROCESSING_BATCH_LIMIT
        self.is_batch = is_batch

    def start(self):
        """
        Initialize upload, get data, and complete upload.
        """
        self.initialize_upload()
        self.get_data_from_csv()
        self.complete_upload()

    def initialize_upload(self):
        """
        Set status to running, and upload start time to now.
        """
        update_fields = ['stop_upload', 'status']
        if not self.upload.upload_start:
            self.upload.upload_start = django_tz.now()
            self.upload.save(update_fields=['upload_start'])
            update_fields.append('upload_start')

        self.upload.stop_upload = False
        self.upload.status = self.upload.Status.RUNNING
        self.upload.save(update_fields=update_fields)

    def requeue_task(self):
        raise NotImplementedError(
            "Children of ProcessUpload should implement requeue_task "
            "so they can handle graceful termination.",
        )

    def process_rows_as_batch(self, reader):
        """
        Process records as batch.
        """
        row_list = [row for row in reader]
        valid_rows = self.get_all_valid_rows(row_list)
        for batch in get_batch(valid_rows, self.batch_limit):
            process_row = self.continue_processing_row()
            if process_row not in [self.SKIP, self.STOP]:
                self.process_records_from_csv_batch(batch)

    def process_each_row(self, reader):
        """
        Process records one by one.
        """
        for row in reader:
            process_row = self.continue_processing_row()
            if process_row == self.CONTINUE:
                self.process_record_from_csv_row(row)
                self.increment_last_row_processed()
            elif process_row == self.STOP:
                break

    def get_data_from_csv(self):  # noqa: C901
        """
        Get data from csv file.
        """
        row = None
        try:
            reader = self.read_csv()
            # Move to the last row processed, this happens when the upload is restarted.
            i = 0
            while i < self.upload.last_row_processed:
                next(reader)
                i += 1

            if self.is_batch:
                self.process_rows_as_batch(reader)
            else:
                self.process_each_row(reader)

            # Check if we're really at the end before marking as complete in case of restart.
            self.upload.refresh_from_db()
            if any([
                self.upload.last_row_processed == self.upload.total_rows,
                self.upload.company.is_demo and  # noqa: W504
                    self.upload.last_row_processed >= 50 and self.upload_type == 'skip_trace',
            ]):
                self.success = True
        except (ConnectionError, ChunkedEncodingError):
            # Every now and then there's an error raised and the upload session simply needs to be
            # restarted.
            self.upload.status = self.upload.Status.ERROR
            self.upload.save(update_fields=['status'])
            self.upload.restart()
        except SystemExit:
            self.upload.status = self.upload.Status.AUTO_STOP
            self.upload.stop_upload = False
            self.upload.save(update_fields=['status', 'stop_upload'])
            self.requeue_task()
            raise
        except:  # noqa E722
            # Error reading csv or processing record.
            error_message = traceback.format_exc()
            error_message += '\n\nCould not access row.' if not row else f'\n\nRow:\n{row}'
            self.upload.upload_error = error_message
            self.set_error(error_message)
            self.success = False
            # Raise error so we see this in Sentry.
            raise

    def complete_upload(self):
        """
        If upload was successful, set status as complete.
        """
        if self.success:
            self.upload.status = self.upload.Status.COMPLETE
            self.upload.upload_end = django_tz.now()
            self.upload.save(update_fields=['status', 'upload_end'])

    def process_record_from_csv_row(self, row):
        """
        Process a single record from a row.

        Code will change depending on the upload. Child class must implement.
        """
        raise NotImplementedError(
            "process_record_from_csv_row is required for classes inherited from ProcessUpload.",
        )

    def increment_last_row_processed(self):
        """
        Increment last row processed
        """
        self.upload.last_row_processed = F('last_row_processed') + 1
        self.upload.save(update_fields=['last_row_processed'])

    def set_error(self, error_message):
        """
        Set error to error message passed.

        :param error_message: Error message to save.
        """
        self.upload.upload_error = error_message
        self.upload.status = self.upload.Status.ERROR
        self.upload.save(update_fields=['upload_error', 'status'])

    def read_csv(self):
        """
        Open csv in path and return reader.
        """
        with default_storage.open(self.upload.path, "r") as csv_file:
            data = csv_file.read()
            if not type(data) == str:
                enc = chardet.detect(data)
                data = data.decode(enc['encoding'])
        data = data.replace('\r\n', '\n')
        data = data.replace('\r', '\n')
        data = StringIO(data)
        data.seek(0)
        print(data, type(data))
        return csv.reader(data)

    def continue_processing_row(self):
        """
        Continue processing this row, skip it, or stop upload?
        """
        stop_check = self.upload_model.objects.get(id=self.upload.id)
        if stop_check.status == 'cancelled':
            stop_check.stop_upload = True
            stop_check.save(update_fields=['stop_upload'])
            self.cancelled = True
            return self.STOP
        if stop_check.stop_upload:
            if stop_check.status != 'auto_stop':
                stop_check.status = 'paused'
                stop_check.save(update_fields=['status'])
            return self.STOP

        # Demo accounts should only be able to process 50 rows for skip trace.
        if all([self.upload_type == 'skip_trace',
                stop_check.company.is_demo,
                stop_check.last_row_processed >= 51,
                ]):
            return self.STOP

        # If this is the header row, skip and mark header as processed.
        if self.upload.has_header_row and not self.processed_header:
            self.processed_header = True
            return self.SKIP

        return self.CONTINUE

    def get_all_valid_rows(self, rows):
        """
        Getting total number of records to process with company restriction
        and previous partially processed file condition.
        """
        if self.upload.has_header_row and not self.processed_header:
            self.processed_header = True
            rows = rows[1:]

        if not self.upload.company.is_demo or len(rows) <= self.demo_limit:
            return rows

        # Demo company loaded a file with more records than the limit
        stop_check = self.upload_model.objects.get(id=self.upload.id)
        current_processed_row = stop_check.last_row_processed
        end_index = self.demo_limit - current_processed_row

        if current_processed_row == 0:
            rows = rows[:self.demo_limit]
        elif end_index <= 0:
            rows = []
        else:
            rows = rows[current_processed_row:current_processed_row + end_index]
        return rows
