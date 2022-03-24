import csv
from datetime import datetime, timedelta

from celery import shared_task
import chardet
from dateutil.parser import parse
from pypodio2.transport import TransportException

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import MultipleObjectsReturned
from django.core.files.storage import default_storage
from django.db.models import Count, Q, Sum
from django.utils import timezone

from billing.models import Transaction
from companies.models import CompanyUploadHistory, PodioFieldMapping, PodioProspectItem
from core.utils import clean_phone
from services.crm.podio import podio, utils
from services.freshsuccess import FreshsuccessClient, get_dimensions
from sherpa.models import (
    CampaignProspect,
    Company,
    InternalDNC,
    PhoneNumber,
    PhoneType,
    Prospect,
    RoiStat,
    SherpaTask,
    SMSMessage,
    SubscriptionCancellationRequest,
    UpdateMonthlyUploadLimit,
    UploadInternalDNC,
)
from sherpa.tasks import sherpa_send_email
from skiptrace.models import UploadSkipTrace
from .models import CompanyChurn, DownloadHistory
from .utils import handle_bulk_file_download, handle_single_file_download

User = get_user_model()


@shared_task
def update_monthly_upload_limit_task():
    """
    Nightly task to go through the upload monthly limit model and see if any companies need their
    prospect limit changed.
    """
    now = timezone.now()
    update_company_list = UpdateMonthlyUploadLimit.objects.filter(
        status='open', update_date__lte=now)

    for update_company in update_company_list:
        company = update_company.company
        company.monthly_upload_limit = update_company.new_monthly_upload_limit
        company.save(update_fields=['monthly_upload_limit'])

        update_company.status = 'complete'
        update_company.save(update_fields=['status'])


@shared_task  # noqa: C901
def upload_internal_dnc_task(upload_internal_dnc_id):
    """
    Uploader for company to import their own dnc phone numbers.
    """
    # ==================== Get objects ====================
    upload_internal_dnc = UploadInternalDNC.objects.get(id=upload_internal_dnc_id)
    company = upload_internal_dnc.company

    # ==================== Open File ====================
    data = None
    if upload_internal_dnc.file:
        path = upload_internal_dnc.file.name
    else:
        path = upload_internal_dnc.path

    with default_storage.open(path, 'r') as csvfile:
        data = csvfile.read()

    if not type(data) == str:
        enc = chardet.detect(data)
        data = data.decode(enc['encoding'])
    data = data.replace('\r\n', '\n')
    data = data.replace('\r', '\n')
    data = data.split('\n')

    # ================= Process File Data =================

    upload_internal_dnc.total_rows = len(data) - (1 if upload_internal_dnc.has_column_header else 0)
    upload_internal_dnc.stop_upload = False
    upload_internal_dnc.status = 'running'
    upload_internal_dnc.save(update_fields=['stop_upload', 'status', 'total_rows'])

    row_count = upload_internal_dnc.last_row_processed
    reader = csv.reader(data)
    if row_count > 0:
        i = 0
        while i < row_count:
            next(reader)
            i += 1
    for row in reader:
        stop_check = UploadInternalDNC.objects.get(id=upload_internal_dnc_id)
        if stop_check.stop_upload and stop_check.status != 'auto_stop':
            stop_check.status = 'stopped'
            stop_check.save(update_fields=['status'])
            break

        row_count += 1

        try:
            phone_number_raw = row[0]
            phone_number_clean = clean_phone(phone_number_raw)
        except IndexError:
            phone_number_clean = ''

        if phone_number_clean:
            try:
                # It is possible on the data level that `InternalDNC` instances are duplicated.
                _, is_new = InternalDNC.objects.get_or_create(
                    phone_raw=phone_number_clean, company=company)
            except MultipleObjectsReturned:
                is_new = False

            if is_new:
                upload_internal_dnc.total_phone_numbers_saved = \
                    upload_internal_dnc.total_phone_numbers_saved + 1

            # Mark the prospects as dnc if they already exist in system.
            prospect = company.prospect_set.filter(phone_raw=phone_number_clean).first()
            if prospect:
                prospect.toggle_do_not_call(None, True)

        upload_internal_dnc.last_row_processed = row_count
        if upload_internal_dnc.total_rows <= row_count:
            upload_internal_dnc.status = 'complete'
            upload_internal_dnc.save(update_fields=['status'])
            return

        upload_internal_dnc.save(update_fields=['total_phone_numbers_saved', 'last_row_processed'])


@shared_task
def bulk_remove_internal_dnc_task(file, user):
    """
    Remove list of phone numbers uploaded in a csv from a company's DNC list.
    """
    total_numbers_removed = 0
    file.seek(0)
    reader = csv.reader(file.read().decode('utf-8').split('\n'))
    for row in reader:
        phone_number_clean = clean_phone(row[0]) if len(row) else None

        if not phone_number_clean:
            continue

        # Delete from InternalDNC and update Prospect.do_not_call to False. Save count returned
        # from delete() and update() so we know the number was deleted and/or updated.
        removed_phone_number, _ = InternalDNC.objects.filter(
            phone_raw=phone_number_clean,
            company=user.profile.company,
        ).delete()
        prospects = Prospect.objects.filter(
            phone_raw=phone_number_clean,
            company=user.profile.company,
            do_not_call=True,
        )
        for prospect in prospects:
            prospect.toggle_do_not_call(user, False)
            removed_phone_number += 1

        # If the number was deleted or updated, then removed_phone_number will be greater than 0 and
        # we want to count this number as removed from the DNC list.
        if removed_phone_number:
            total_numbers_removed += 1

    send_dnc_bulk_remove_email_confirmation_task(user, total_numbers_removed)


def send_dnc_bulk_remove_email_confirmation_task(user, numbers_removed):
    """
    Alerts user that upload is complete
    """
    email_address = user.email

    if email_address:
        subject = 'Bulk Remove from DNC List Complete'
        template = 'email/email_dnc_bulk_remove_confirmation.html'
        context = {'numbers_removed': numbers_removed, 'first_name': user.first_name}

        sherpa_send_email.delay(subject, template, email_address, context)


@shared_task
def update_churn_stats():
    """
    Update the records for `CompanyChurn` with their churn indicators.
    """
    valid_companies = Company.objects.exclude(Q(subscription_id="") | Q(subscription_id=None))

    for subscription_company in valid_companies:
        churn_instance, created = CompanyChurn.objects.get_or_create(company=subscription_company)

    for churn_company in CompanyChurn.objects.prefetch_related('company').all():
        company = churn_company.company
        if company not in valid_companies:
            # Company is no longer a valid subscriber
            churn_company.delete()
            continue

        try:
            churn_company.days_until_subscription = company.days_until_subscription
            churn_company.prospect_upload_percent = company.prospect_upload_percent
            churn_company.save()
        except TypeError:
            # Trial companies don't have a start/end billing date yet.
            churn_company.delete()


@shared_task  # noqa:C901
def update_roi_stats(start_date=None):
    """
    This command will calculate all the ROI stats for sherpa by finding all the revenue and expense
    and calculating data on the profits for each company.
    """
    for roi_stat in RoiStat.objects.all():
        roi_stat.delete()

    # Setup the start and end dates for the ROI period
    now = timezone.now()
    ago = timedelta(days=90)
    period_start = timezone.make_aware(parse(start_date)) if start_date else now - ago
    period_end = now

    company_list = Company.objects.filter(braintree_id__isnull=False)

    for company in company_list:
        """
        Loop through all the eligible companies and get each of their revenue and expense amounts.
        """
        # =============== Subscription Sum ===============
        transaction_subscription_sum_dict = Transaction.objects.filter(
            company=company,
            type=Transaction.Type.SUBSCRIPTION,
            dt_charged__gte=period_start,
            dt_charged__lte=period_end,
        ).aggregate(
            Sum('amount_charged'),
            subscription_fee_count=Count('amount_charged'),
        )
        transaction_subscription_sum = transaction_subscription_sum_dict.get(
            "amount_charged__sum", 0)
        if not transaction_subscription_sum:
            transaction_subscription_sum = 0
        transaction_subscription_count = transaction_subscription_sum_dict.get(
            "subscription_fee_count", 0)
        if not transaction_subscription_count:
            transaction_subscription_count = 0

        # =============== Skip Trace Sum ===============
        transaction_skip_trace_sum_dict = Transaction.objects.filter(
            company=company,
            type='skip trace fee',
            dt_charged__gte=period_start,
            dt_charged__lte=period_end,
        ).aggregate(
            Sum('amount_charged'),
            skip_trace_fee_count=Count('amount_charged'),
        )
        transaction_skip_trace_sum = transaction_skip_trace_sum_dict.get("amount_charged__sum", 0)
        if not transaction_skip_trace_sum:
            transaction_skip_trace_sum = 0
        transaction_skip_trace_count = transaction_skip_trace_sum_dict.get(
            "skip_trace_fee_count", 0)
        if not transaction_skip_trace_count:
            transaction_skip_trace_count = 0

        skip_traces = UploadSkipTrace.objects.filter(
            company=company,
            upload_end__gte=period_start,
            upload_end__lte=period_end,
        )

        count_skip_trace_hits = skip_traces.aggregate(
            Sum('total_billable_hits'),
        ).get('total_billable_hits__sum') or 0
        count_skip_trace_uploads = skip_traces.count()

        # =============== Additional Uploads Sum ===============
        transaction_upload_sum_dict = Transaction.objects.filter(
            company=company,
            type='upload fee',
            dt_charged__gte=period_start,
            dt_charged__lte=period_end,
        ).aggregate(
            Sum('amount_charged'),
            upload_fee_count=Count('amount_charged'),
        )
        transaction_upload_sum = transaction_upload_sum_dict.get("amount_charged__sum", 0)
        if not transaction_upload_sum:
            transaction_upload_sum = 0
        transaction_upload_count = transaction_upload_sum_dict.get("upload_fee_count", 0)
        if not transaction_upload_count:
            transaction_upload_count = 0

        # =============== Other Sum ===============
        transaction_other_sum_dict = Transaction.objects.filter(
            company=company,
            type='other',
            dt_charged__gte=period_start,
            dt_charged__lte=period_end,
        ).aggregate(
            Sum('amount_charged'),
            other_fee_count=Count('amount_charged'),
        )
        transaction_other_sum = transaction_other_sum_dict.get("amount_charged__sum", 0)
        if not transaction_other_sum:
            transaction_other_sum = 0
        transaction_other_count = transaction_other_sum_dict.get("other_fee_count", 0)
        if not transaction_other_count:
            transaction_other_count = 0

        # =============== Total SMS Sent/Received Counts ===============
        sms_sent_and_received_count = SMSMessage.objects.filter(
            Q(company_id=company.pk),
            Q(dt__gte=period_start),
            Q(dt__lte=period_end),
        ).values(
            "company_id",
        ).annotate(
            count_from_prospect=Count("pk", filter=Q(from_prospect=True)),
            count_not_from_prospect=Count("pk", filter=~Q(from_prospect=True)),
        )[0]

        count_sms_sent = sms_sent_and_received_count['count_not_from_prospect']
        count_sms_received = sms_sent_and_received_count['count_from_prospect']

        # =============== Total Phone Lookup Count ===============
        count_phone_type_lookup = PhoneType.objects.filter(
            company=company,
            checked_datetime__gte=period_start,
            checked_datetime__lte=period_end,
        ).count()

        # =============== Total Prospects added  ===============
        count_prospects = company.prospect_set.filter(
            created_date__gte=period_start,
            created_date__lte=period_end,
        ).count()

        # =============== Total UNIQUE Prospects added (counts against limit) ===============
        count_unique_prospects = CampaignProspect.objects.filter(
            prospect__company=company,
            include_in_upload_count=True,
            created_date__gte=period_start,
            created_date__lte=period_end,
        ).count()

        # =============== Total Phone Number Count ===============
        count_phone_numbers = PhoneNumber.objects.filter(
            company=company, status='active').count()

        # =============== Save Stats ==============
        if company.subscription:
            next_billing_date = company.subscription.next_billing_date
        else:
            next_billing_date = None

        RoiStat.objects.create(
            company=company,
            period_start=period_start,
            period_end=period_end,
            revenue_subscription=transaction_subscription_sum,
            revenue_subscription_count=transaction_subscription_count,
            revenue_skip_trace=transaction_skip_trace_sum,
            revenue_skip_trace_count=transaction_skip_trace_count,
            revenue_additional_uploads=transaction_upload_sum,
            revenue_additional_uploads_count=transaction_upload_count,
            revenue_other=transaction_other_sum,
            revenue_other_count=transaction_other_count,
            count_sms_sent=count_sms_sent,
            count_sms_received=count_sms_received,
            count_phone_type_lookup=count_phone_type_lookup,
            count_prospects=count_prospects,
            count_unique_prospects=count_unique_prospects,
            subscription_signup_date=company.subscription_signup_date,
            count_phone_numbers=count_phone_numbers,
            next_billing_date=next_billing_date,
            count_skip_trace_hits=count_skip_trace_hits,
            count_skip_trace_uploads=count_skip_trace_uploads,
        )


@shared_task
def modify_freshsuccess_account(company_id):
    """
    Create a freshsuccess account for the company.

    When a new company signs up, we will create a new freshsuccess account for them with their vital
    statistics to help improve their experience rate and reduce churn.
    """
    if settings.TEST_MODE:
        return

    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        # Sometimes we see that the company does not exist yet.
        return

    client = FreshsuccessClient()

    # Add a list of custom dimensions from properties of the company. Natero has it set up so that
    # each data type of dimensions has its own key in payload, so we have the data split out into
    # objects.
    #
    # dimension_type: The natero dimension type can be value (number), date (date) or label (str)
    # source_property_name: The name of the property to get from company or source_obj.
    # source_obj (optional): Override the object to pull the property from, in case the property
    #     does not come from company.
    # fs_dimension_name (optional): Override the property name that will be used in FS for the
    #     custom dimension.
    dimensions = get_dimensions(company)

    custom_value_dimensions = []
    custom_label_dimensions = []
    custom_event_dimensions = []

    # Go through each field and add it to its respective list.
    for dimension in dimensions:
        dimension_type = dimension.get('dimension_type')
        dimension_field = dimension.get('source_property_name')
        obj = dimension.get('source_subobj', company)

        # Depending on the data type of the dimension, we need to add it differently to FS.
        if dimension_type == 'value':
            dimension_list = custom_value_dimensions
            value = getattr(obj, dimension_field)
        elif dimension_type == 'label':
            dimension_list = custom_label_dimensions
            value = getattr(obj, dimension_field)
        elif dimension_type == 'date':
            dimension_list = custom_event_dimensions
            # Sometimes the datetime can actually come as a date.
            datetime_value = getattr(obj, dimension_field)
            if type(datetime_value) == datetime:
                datetime_value = datetime_value.date()
            value = int(datetime_value.strftime("%s")) * 1000 if datetime_value else None

        # Get the dimension name based on the property field name or overrided dimension name.
        dimension_name = dimension.get(
            'fs_dimension_name',
            dimension_field.replace('_', ' ').capitalize(),
        )
        dimension_list.append({
            "key": dimension_name,
            "value": value,
        })

    payload = {
        'account_id': company.id,
        'name': company.name,
        'join_date': company.created_timestamp,
        'billing_account_id': company.braintree_id,
        "custom_value_dimensions": custom_value_dimensions,
        "custom_label_dimensions": custom_label_dimensions,
        "custom_event_dimensions": custom_event_dimensions,
    }
    return client.create('accounts', payload)


@shared_task
def process_cancellation_requests():
    """
    Companies create cancellation requests and cancel at the end of their subscriptions. This will
    look at which companies are due to cancel and process those cancellations.
    """
    subscription_cancellation_list = SubscriptionCancellationRequest.objects.filter(
        status=SubscriptionCancellationRequest.Status.ACCEPTED_PENDING,
        cancellation_date__lte=timezone.now(),
    )

    for subscription_cancellation in subscription_cancellation_list:
        company = subscription_cancellation.company
        if subscription_cancellation.pause:
            company.pause_subscription(subscription_cancellation=subscription_cancellation)
        else:
            company.cancel_subscription(subscription_cancellation=subscription_cancellation)


@shared_task
def release_cancelled_numbers():
    """
    Sometimes companies have cancelled subscriptions but for some reason they did not get released
    when the cancellation request was fulfilled. This task will go through and releaes all the
    numbers from cancelled companies if they have active numbers.
    """
    queryset = Company.objects.filter(subscription_status=Company.SubscriptionStatus.CANCELED)
    for company in queryset:
        # Check if the cancelled company has active numbers.
        non_released_numbers = company.phone_numbers.exclude(status=PhoneNumber.Status.RELEASED)
        if not non_released_numbers:
            continue

        # Don't release until a cancellation request has finished.
        cancel_req = company.cancellation_requests.first()
        if cancel_req and cancel_req.status != SubscriptionCancellationRequest.Status.COMPLETE:
            continue

        for phone_number in non_released_numbers:
            phone_number.release()


@shared_task
def generate_download(download_uuid, post_download_method=None):
    """
    Generates the download files that will be saved in storage (S3).

    :param download_uuid UUID: The DownloadHistory uuid that will be used to locate the filters.
    :param post_download_method: Name of optional method on Company to run after download that
    takes user as a parameter
    """
    try:
        download = DownloadHistory.objects.get(uuid=download_uuid)
    except DownloadHistory.DoesNotExist:
        return
    download.status = DownloadHistory.Status.RUNNING
    download.save(update_fields=['status'])

    if not download.is_bulk:
        handle_single_file_download(download)
    else:
        handle_bulk_file_download(download)

    download.status = DownloadHistory.Status.COMPLETE
    download.save(update_fields=['status'])

    # Run post download method if there is one.
    if post_download_method:
        getattr(download.company, post_download_method)(download.created_by)


@shared_task
def reset_monthly_upload_count():
    """
    Reset monthly upload count when new billing period starts.
    """
    company_queryset = Company.objects.exclude(
        subscription_status=Company.SubscriptionStatus.CANCELED,
    ).exclude(subscription_status__isnull=True)
    for company in company_queryset:
        subscription = company.subscription

        if not subscription:
            continue

        start_billing_date = subscription.billing_period_start_date
        end_billing_date = subscription.billing_period_end_date
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        if start_billing_date == today or end_billing_date == yesterday:
            # Create a new record for the company history. The subscription may have already moved
            # to the next month, but braintree is sometimes delayed so we just can use yesterday.
            previous_end_billing_date = yesterday

            if previous_end_billing_date.month == 1:
                # If in January, last month was December.
                previous_start_billing_date = start_billing_date.replace(
                    month=12, year=start_billing_date.year - 1)
            else:
                try:
                    previous_start_billing_date = start_billing_date.replace(
                        month=start_billing_date.month - 1)
                except ValueError:
                    # Previous month does not have this day, take the last day of last month.
                    previous_start_billing_date = start_billing_date.replace(
                        day=1) - timedelta(days=1)

            CompanyUploadHistory.objects.get_or_create(
                company=company,
                start_billing_date=previous_start_billing_date,
                defaults={
                    'end_billing_date': previous_end_billing_date,
                    'upload_count': company.monthly_upload_count,
                },
            )
            company.monthly_upload_count = 0
            company.save(update_fields=['monthly_upload_count'])


@shared_task
def set_freshsuccess_billing(company_id):
    """
    Sets the billing id in freshsuccess so that the company's billing data is linked.
    """
    company = Company.objects.get(id=company_id)
    fresh_client = FreshsuccessClient()
    payload = {'billing_account_id': company.braintree_id}
    fresh_client.update('accounts', company.id, payload)


def sync_prospect_messages_to_podio(client, prospect, item_id):
    """Sync the prospect messages to podio after a successful prospect sync

    :param client PodioClient: Podio Client instance to interact with podio
    :param prospect Prospect:  The Prospect we're syncing
    :param item_id  Int:       Item id that was returned by podio after syncing the prospect
    """
    existing_comments = client.api.Comment.get_comments_for_item(item_id)\
                                          .get('response')\
                                          .get('data', [])
    existing_comment_ids = [comment['external_id'] for comment in existing_comments]

    for message in prospect.messages.all():
        message_id = str(message.pk)

        if message_id not in existing_comment_ids:
            date = str(message.dt.date())
            message_string = f'**From: {message.from_name}**\n**{date}**\n{message.message}'
            payload = {
                'value': message_string,
                'external_id': message_id,
            }
            client.api.Comment.create('item', str(item_id), payload)


def push_data_to_podio_error_rollback(attributes, prospect, task, e: Exception):
    if prospect is not None:
        # auto-qualify prospect if successfully pushed to podio
        user = User.objects.get(pk=attributes.get('user_id'))
        updated_instance, activities = prospect.toggle_qualified_lead(user, True)
        updated_instance.activities = activities
        updated_instance.save()
    task.set_error(error_msg=str(e))


@shared_task
def push_data_to_podio(task_id):
    """Task to export the prospect data and sync it to podio"""
    task = SherpaTask.objects.get(pk=task_id)

    if task.pause:
        return

    task.start_task()
    attributes = task.attributes

    prospect = None
    try:
        # Get the Podio Integration Object for the company stored in the task
        podio_integration = task.company.companypodiocrm_set.first()

        # Raise an error if user does not have a podio integration
        if not podio_integration:
            raise Exception("No podio integration found")

        # push all the fields related to the podio record
        tokens = {
            "access": podio_integration.access_token,
            "refresh": podio_integration.refresh_token,
            "expires_in": podio_integration.expires_in_token,
        }
        client = podio.PodioClient(
            task.company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
            tokens,
        )
        client.authenticate()

        # get the mapping fields
        response = None
        field_mapping = PodioFieldMapping.objects.get(company=task.company)

        data_to_sync = utils.fetch_data_to_sync(field_mapping, attributes)
        app_id = podio_integration.application

        podio_prospect_item = PodioProspectItem.objects.filter(
            prospect=attributes.get('prospect_id'),
        )
        item_id = None

        if(podio_prospect_item.exists()):
            prospect_item = podio_prospect_item.first()
            prospect = prospect_item.prospect
            item_id = prospect_item.item_id
            response = client.api.Item.update(item_id, data_to_sync)
        else:
            response = client.api.Item.create(app_id, data_to_sync)
            item_id = response['response']['data']['item_id']

            prospect = Prospect.objects.get(pk=attributes.get('prospect_id'))
            PodioProspectItem.objects.create(prospect=prospect, item_id=item_id)

        # sync the messages
        sync_prospect_messages_to_podio(client, prospect, item_id)

        task.complete_task()

    except TransportException as e:
        push_data_to_podio_error_rollback(attributes, prospect, task, e)
        task.restart_task()
    except Exception as e:
        push_data_to_podio_error_rollback(attributes, prospect, task, e)
