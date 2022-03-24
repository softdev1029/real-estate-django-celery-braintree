import csv
from io import BytesIO, TextIOWrapper
import uuid

from celery import shared_task
import chardet
import unicodecsv

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core.utils import clean_phone
from services.smarty import SmartyValidateAddresses
from sherpa.models import LitigatorCheck, LitigatorList, UploadLitigatorCheck, UploadLitigatorList
from sherpa.utils import get_data_from_column_mapping


@shared_task  # noqa: C901
def litigator_check_task(upload_litigator_check_id):
    """
    Check if phone numbers is on litigator list.
    """
    # ==================== Get objects ====================

    upload_litigator_check = UploadLitigatorCheck.objects.get(id=upload_litigator_check_id)

    # ==================== Open File ====================

    path = upload_litigator_check.path
    data = None
    with default_storage.open(path, 'r') as csvfile:
        data = csvfile.read()
        if not type(data) == str:
            enc = chardet.detect(data)
            data = data.decode(enc['encoding'])
    data = data.replace('\r\n', '\n')
    data = data.replace('\r', '\n')
    data = BytesIO(data.encode('UTF-8'))
    data.seek(0)

    # ================= Process File Data =================

    upload_litigator_check.stop_upload = False
    upload_litigator_check.status = 'litigator scrub'
    upload_litigator_check.save(update_fields=['stop_upload', 'status'])

    row_count = upload_litigator_check.last_row_processed
    reader = unicodecsv.reader(data)
    if row_count > 0:
        i = 0
        while i < row_count:
            next(reader)
            i += 1

    for row in reader:
        stop_check = UploadLitigatorCheck.objects.get(id=upload_litigator_check_id)
        if stop_check.stop_upload:
            if stop_check.status != 'auto_stop':
                stop_check.status = 'paused'
                stop_check.save(update_fields=['status'])
            break

        row_count += 1

        if upload_litigator_check.has_header_row and row_count == 1:
            # skipping over header row
            continue

        # === Build phone number list - loop through up to 12 phone number fields ===
        phone_list = []
        for phone_field_num in range(3):
            field_num = int(phone_field_num) + 1
            phone_column_number = getattr(upload_litigator_check, 'phone_%d_number' % field_num)
            if phone_column_number is not None and phone_column_number != '':
                phone_raw = row[int(phone_column_number)]
                phone_clean = clean_phone(phone_raw)
                if phone_clean:
                    phone_list.append(phone_clean)
            else:
                break

        # === Check if any phone numbers are a litigator or complainer ===
        has_litigator_associated = False
        litigator_phone_list = []
        complainer_phone_list = []
        for ph in phone_list:
            litigator_list = LitigatorList.objects.filter(phone=ph)
            if len(litigator_list) > 0:
                ll = litigator_list[0]
                if ll.type == 'Litigator':
                    litigator_phone_list.append(ph)
                else:
                    complainer_phone_list.append(ph)
                has_litigator_associated = True

        related_record_id = str(uuid.uuid4())

        is_first_record = True
        column_fields = [
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
            'custom_1',
            'custom_2',
            'custom_3',
            'email',
        ]

        data = get_data_from_column_mapping(column_fields, row, upload_litigator_check)

        litigator_type = ''
        sort_order = 9
        for index, phone in enumerate(phone_list):
            data[f'phone_{index + 1}_number'] = phone
            # Check if on litigator or complainer list here
            if phone in litigator_phone_list:
                litigator_type = LitigatorCheck.Type.SERIAL
                sort_order = 1
            elif phone in complainer_phone_list:
                litigator_type = LitigatorCheck.Type.PRE
                sort_order = 2
            elif has_litigator_associated:
                litigator_type = LitigatorCheck.Type.ASSOCIATED
                sort_order = 3

        LitigatorCheck.objects.create(
            upload_litigator_check=upload_litigator_check,
            phone1=data.get('phone_1_number', ''),
            phone2=data.get('phone_2_number', ''),
            phone3=data.get('phone_3_number', ''),
            fullname=data['fullname'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            mailing_address=data['mailing_street'],
            mailing_city=data['mailing_city'],
            mailing_state=data['mailing_state'],
            mailing_zip=data['mailing_zipcode'],
            property_address=data['street'],
            property_city=data['city'],
            property_state=data['state'],
            property_zip=data['zipcode'],
            related_record_id=related_record_id,
            is_first_record=is_first_record,
            email=data['email'],
            custom1=data['custom_1'],
            custom2=data['custom_2'],
            custom3=data['custom_3'],
            litigator_type=litigator_type,
            sort_order=sort_order,
        )

        upload_litigator_check.last_row_processed = row_count

        if upload_litigator_check.total_rows <= row_count:
            upload_litigator_check.status = 'validating'
            validate_batch_address_litigator_check_task.delay(upload_litigator_check.id)

        upload_litigator_check.save(update_fields=['last_row_processed', 'status'])


@shared_task  # noqa: C901
def upload_litigator_list_task(upload_litigator_id):
    """
    Internal sherpa uploader to populate database with potential litigators
    """
    # ==================== Get objects ====================
    upload_litigator_list = UploadLitigatorList.objects.get(id=upload_litigator_id)

    litigator_list_type = upload_litigator_list.litigator_list_type

    # ================= Open & Process File Data =================
    upload_file = upload_litigator_list.file
    upload_file.open()
    with TextIOWrapper(upload_file, encoding='utf-8') as csv_file:
        upload_litigator_list.stop_upload = False
        upload_litigator_list.status = 'running'
        upload_litigator_list.save()
        row_count = upload_litigator_list.last_row_processed
        reader = csv.reader(csv_file)
        if row_count > 0:
            i = 0
            while i < row_count:
                next(reader)
                i += 1
        for row in reader:
            upload_litigator_list.refresh_from_db()
            if upload_litigator_list.stop_upload:
                upload_litigator_list.status = 'stopped'
                upload_litigator_list.save(update_fields=['status'])
                upload_file.close()
                return

            row_count += 1

            try:
                phone_number_raw = row[0]
                phone_number_clean = clean_phone(phone_number_raw)
            except:  # noqa: E722
                phone_number_clean = ''

            if phone_number_clean:
                litigator_list, is_new = LitigatorList.objects.get_or_create(
                    phone=phone_number_clean,
                )
                litigator_list.type = litigator_list_type
                litigator_list.save()

                if is_new:
                    upload_litigator_list.last_numbers_saved = \
                        upload_litigator_list.last_numbers_saved + 1

            upload_litigator_list.last_row_processed = row_count
            upload_litigator_list.save(update_fields=['last_numbers_saved', 'last_row_processed'])

    upload_file.close()
    upload_litigator_list.total_rows = row_count
    upload_litigator_list.status = UploadLitigatorList.Status.COMPLETE
    upload_litigator_list.save(update_fields=['total_rows', 'status'])

    if not upload_litigator_list.confirmation_email_sent:
        email_address = 'jason@leadsherpa.com'
        cc_email = 'support@leadsherpa.com'

        subject = 'Litigator Upload Complete - Ref# %s' % upload_litigator_list.id
        from_email = settings.DEFAULT_FROM_EMAIL
        to = email_address
        text_content = 'Litigator Scrub Complete'
        html_content = render_to_string('email/email_upload_litigator_complete.html',
                                        {'upload_litigator_list': upload_litigator_list})
        email = EmailMultiAlternatives(
            subject,
            text_content,
            from_email,
            [to],
            cc=[cc_email],
        )
        email.attach_alternative(html_content, "text/html")
        email.send()

        upload_litigator_list.confirmation_email_sent = True
        upload_litigator_list.save(update_fields=['confirmation_email_sent'])


@shared_task
def validate_batch_address_litigator_check_task(upload_litigator_check_id):
    """
    Validate addresses with SmartyStreet from litigator check.
    """
    upload_litigator_check = UploadLitigatorCheck.objects.get(id=upload_litigator_check_id)

    litigator_check_list = LitigatorCheck.objects.filter(
        upload_litigator_check=upload_litigator_check,
        validated_property_status=None,
    )[:100]

    for litigator_check in litigator_check_list:
        validator = SmartyValidateAddresses(litigator_check, has_submitted_prefix=False)
        validator.validate_addresses()

    if len(litigator_check_list) > 0:
        validate_batch_address_litigator_check_task.delay(upload_litigator_check_id)
    else:
        upload_litigator_check.status = 'complete'
        upload_litigator_check.save()

        # Send "Complete" email here
        if not upload_litigator_check.email_completed_sent:
            try:
                check_litigator_hash = upload_litigator_check.token
                ref_id_raw = check_litigator_hash[:5]
                ref_id = ref_id_raw.replace("-", "7")
            except:  # noqa: E722
                ref_id = '82076'
            site = Site.objects.get_current()
            email_address = upload_litigator_check.email_address
            subject = 'Litigator Scrub Complete - Ref# %s' % ref_id
            from_email = settings.DEFAULT_FROM_EMAIL
            to = email_address
            text_content = 'Litigator Scrub Complete'
            html_content = render_to_string(
                'email/email_litigator_check_complete.html',
                {
                    'site': site,
                    'upload_litigator_check': upload_litigator_check,
                },
            )
            email = EmailMultiAlternatives(subject, text_content, from_email, [to])
            email.attach_alternative(html_content, "text/html")

            email.send()

        upload_litigator_check.email_completed_sent = True
