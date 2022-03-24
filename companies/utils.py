import csv
from io import BytesIO
import os
from zipfile import ZipFile

from dateutil import parser

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.files.base import ContentFile
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from campaigns.resources import CampaignResource
from campaigns.utils import get_campaigns_by_access
from companies.resources import CampaignMetaStatsResource, ProfileStatsResource
from properties.models import Property
from properties.resources import PropertyResource
from prospects.resources import CampaignProspectResource, ProspectResource
from sherpa.models import Campaign, InternalDNC, LeadStage, Prospect
from sherpa.tasks import sherpa_send_email
from skiptrace.models import SkipTraceProperty
from skiptrace.resources import SkipTraceResource
from .models import DownloadHistory
from .resources import DNCResource


def generate_campaign_prospect_filters(filters):
    lead_stage = None
    if filters['lead_stage_id'] and int(filters.get('lead_stage_id', 0)) > 0:
        lead_stage = LeadStage.objects.get(id=filters['lead_stage_id'])

    return {
        'lead_stage': lead_stage,
        'is_priority_unread': filters['is_priority_unread'],
        'phone_type': filters['phone_type'],
    }


def handle_single_file_download(download):  # noqa C901
    """
    Generates a single CSV file of a specific type and saves it to the download file storage
    location.
    """
    resource = None
    filters = download.filters
    filename = filters.pop('filename')
    if download.download_type == DownloadHistory.DownloadTypes.CAMPAIGN_PROSPECT:
        campaign = Campaign.objects.get(id=filters['campaign_id'])
        if campaign.is_direct_mail:
            queryset = campaign.campaignprospect_set.filter(removed_datetime__isnull=True)
        else:
            queryset = campaign.build_export_query(
                generate_campaign_prospect_filters(filters),
            )
        resource = CampaignProspectResource().export(download, queryset)
    elif download.download_type == DownloadHistory.DownloadTypes.PROSPECT:
        if filters['ids']:
            queryset = Prospect.objects.filter(id__in=filters['ids'])
        else:
            queryset = Prospect.objects.search(
                download.created_by,
                filters=filters,
            )
        resource = ProspectResource().export(download, queryset)
    elif download.download_type == DownloadHistory.DownloadTypes.PROPERTY:
        queryset = Property.objects.filter(id__in=filters['ids'])
        resource = PropertyResource().export(download, queryset)
    elif download.download_type == DownloadHistory.DownloadTypes.SKIPTRACE:
        queryset = SkipTraceProperty.objects.filter(
            upload_skip_trace_id=filters['upload_skip_trace_id'],
        )
        resource = SkipTraceResource().export(download, queryset)
    elif download.download_type == DownloadHistory.DownloadTypes.DNC:
        company = download.company
        internal_queryset = InternalDNC.objects.filter(company=company).values('phone_raw')
        prospect_queryset = Prospect.objects.filter(
            company=company,
            do_not_call=True,
        ).values('phone_raw')
        queryset = internal_queryset.union(prospect_queryset).order_by('phone_raw')
        resource = DNCResource().export(download, queryset)
    elif download.download_type == DownloadHistory.DownloadTypes.CAMPAIGN:
        campaigns = get_campaigns_by_access(download.created_by)

        min_percent = filters.pop('percent_complete_min', None)
        max_percent = filters.pop('percent_complete_max', None)
        search = filters.pop('search', None)
        order = filters.pop('ordering', ['id'])
        market = filters.pop('market', None)
        if order[0] == '-':
            f_order = F(order[1:]).desc(nulls_last=True)
        else:
            f_order = F(order).asc(nulls_last=True)

        campaigns = campaigns.filter(**filters)
        if market:
            campaigns = campaigns.filter(market=market)
        if min_percent:
            campaigns = campaigns.filter(percent__gte=min_percent)
        if max_percent:
            campaigns = campaigns.filter(percent__lte=max_percent)
        if search:
            campaigns = campaigns.filter(name__icontains=search)

        campaigns = campaigns.order_by(f_order)

        resource = CampaignResource().export(download, campaigns)
    elif download.download_type == DownloadHistory.DownloadTypes.CAMPAIGN_META_STATS:
        data = download.company.campaign_meta_stats(**filters)
        resource = CampaignMetaStatsResource().export(download, data)
    elif download.download_type == DownloadHistory.DownloadTypes.PROFILE_STATS:
        start_date = parser.parse(filters['start_date'])
        end_date = parser.parse(filters['end_date'])
        data = download.company.user_profile_stats(start_date, end_date)
        resource = ProfileStatsResource().export(download, data)

    download.file.save(filename, ContentFile(resource.csv.encode('utf-8')))


def handle_bulk_file_download(download):
    """
    Creates a single zip file containing CSV files of a specific type and saves it to the download
    file storage location.
    """
    filename_date = timezone.now().date()
    data = []
    filters = download.filters
    if download.download_type == DownloadHistory.DownloadTypes.CAMPAIGN_PROSPECT:
        for pk in filters['id_list']:
            campaign = Campaign.objects.get(id=pk)
            filename = f'{ str(campaign) }_{ filename_date }.csv'
            queryset = campaign.campaignprospect_set.all()
            resource = CampaignProspectResource().export(download, queryset)
            data.append([filename, resource.csv.encode('utf-8')])
    if download.download_type == DownloadHistory.DownloadTypes.SKIPTRACE:
        for pk in filters['id_list']:
            filename = f'{ str(download.company) }_{ filename_date }.csv'
            queryset = SkipTraceProperty.objects.filter(
                upload_skip_trace_id=pk,
            )
            resource = SkipTraceResource().export(download, queryset)
            data.append([filename, resource.csv.encode('utf-8')])

    zip_io = BytesIO()
    zipf = ZipFile(zip_io, 'w')
    for d in data:
        zipf.writestr(d[0], d[1])
    zipf.close()
    download.file.save(f'bulk_campaign_{ filename_date }.zip', zip_io)


def verify_dnc_import_file(file_data):
    single_column = False
    has_column_header = False
    reader = csv.reader(file_data.read().decode('utf-8').split('\n'))
    for row in reader:
        single_column = len(row) == 1
        has_column_header = row[0].title() == 'Phone'
        break
    return [single_column, has_column_header]


def handle_cancellation_flow(cancellation_request):
    """
    Based on the SubscriptionCancellationRequest instance data, determines the actions to take
    for the company cancellation request.
    """
    from companies.tasks import modify_freshsuccess_account

    company = cancellation_request.company
    data = {}

    data.update(cancellation_request.handle_discount())
    data.update(cancellation_request.handle_pause())
    data.update(cancellation_request.handle_downgrade())
    cancellation_request.refresh_from_db()

    #  Email sherpa support about the cancellation request.
    site = Site.objects.get(id=settings.SITE_ID)
    sherpa_send_email.delay(
        f"Cancel Request - {company.name}",
        "email/email_cancel_request.html",
        "support@leadsherpa.com",
        {
            "company_name": company.name,
            "reason": cancellation_request.get_cancellation_reason_display(),
            "reason_text": cancellation_request.cancellation_reason_text,
            "id": cancellation_request.id,
            "status": cancellation_request.get_status_display(),
            "domain": site.domain,
        },
    )

    #  Send cancellation request data to Freshsuccess.
    modify_freshsuccess_account.delay(company.id)

    return data


def verify_dnc_upload_files(request):
    """
    Verify all files in DNC Import (or remove).

    Returns a dict with
    1) has_error: Boolean indicating there's an error
    2) files: list of files
    3) error_message: string with error message to display
    """
    results = {'has_error': False, 'files': [], 'error_message': None}
    try:
        for file in request.FILES.getlist('files'):
            [single_column, has_header] = verify_dnc_import_file(file)
            if single_column:
                results["files"].append({'file': file, 'has_header': has_header})
            else:
                results['has_error'] = True
                results['error_message'] = "File has more than one column. Please re-upload with" \
                                           " one column of phone numbers."
    except Exception:
        results["has_error"] = True

    return results


def make_podio_webhook_url(instance_pk):
    """
    Creates a webhook url for podio webhooks.

    :param instance_pk Int:  Company pk
    """
    ngrok_url = os.getenv('NGROK_URL')
    domain = Site.objects.get_current().domain

    if ngrok_url:
        domain = f'http://{ngrok_url}'

    path = reverse('crmpodiowebhooks-items-webhook', args=(instance_pk,))
    return domain + path
