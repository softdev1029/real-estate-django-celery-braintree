import traceback

from celery import shared_task
from smartystreets_python_sdk import Batch
from smartystreets_python_sdk.exceptions import SmartyException
from smartystreets_python_sdk.us_street import Lookup

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.mail import EmailMultiAlternatives
from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils import timezone as django_tz
from django.utils.dateparse import parse_date

from campaigns.utils import push_to_campaign
from services.smarty import smarty_client
from sherpa.models import (
    Campaign,
    CampaignProspect,
    Prospect,
)
from sherpa.tasks import sherpa_send_email
from .models import SkipTraceDailyStats, SkipTraceProperty, UploadSkipTrace


@shared_task
def send_skip_trace_confirmation_task(upload_skip_trace_id):
    """
    Alerts user that skip trace is complete
    """
    upload_skip_trace = UploadSkipTrace.objects.get(id=upload_skip_trace_id)
    rep = upload_skip_trace.created_by

    existing_match_savings = upload_skip_trace.existing_match_savings

    email_address = rep.email

    if email_address and not upload_skip_trace.email_confirmation_sent:

        try:
            cost_per_hit = upload_skip_trace.company.skip_trace_price
            if upload_skip_trace.total_billable_hits > 0:
                calculated_amount = upload_skip_trace.total_billable_hits * cost_per_hit
                # $2 minimum charge about. This can be changed later
                if calculated_amount < 2:
                    calculated_amount = 2
            else:
                calculated_amount = '0.00'
        except:  # noqa:E722
            calculated_amount = 'na'

        show_low_hit_link = False
        try:
            hit_rate = (float(
                upload_skip_trace.total_hits) / upload_skip_trace.last_row_processed) * 100
            if hit_rate < 85:
                show_low_hit_link = True
        except:  # noqa:E722
            pass

        # Send different email depending on bulk or single.
        site_domain = Site.objects.get(id=settings.DJOSER_SITE_ID).domain
        if upload_skip_trace.is_single_upload:
            sherpa_send_email(
                f'Skip Trace Complete - Ref# {upload_skip_trace.id}',
                'email/skip_trace/single_complete.html',
                email_address,
                {
                    'upload_skip_trace': upload_skip_trace,
                    'rep': rep,
                    'application_url': site_domain,
                },
            )
        else:
            sherpa_send_email(
                f'Skip Trace Complete - Ref# {upload_skip_trace.id}',
                'email/skip_trace/bulk_complete.html',
                email_address,
                {
                    'upload_skip_trace': upload_skip_trace,
                    'rep': rep,
                    'existing_match_savings': existing_match_savings,
                    'calculated_amount': calculated_amount,
                    'show_low_hit_link': show_low_hit_link,
                    'application_url': site_domain,
                    'total_litigators': upload_skip_trace.total_litigators,
                },
            )

        upload_skip_trace.email_confirmation_sent = True
        upload_skip_trace.save(update_fields=['email_confirmation_sent'])


@shared_task
def send_skip_trace_error_upload_email_task(upload_skip_trace_id):
    """
    Alerts sherpa support that has issue has occurred with skip trace if there was an error in
    production.
    """
    if not settings.SKIP_TRACE_SEND_ERROR_EMAIL:
        return

    upload_skip_trace = UploadSkipTrace.objects.get(id=upload_skip_trace_id)

    email_address = 'support@leadsherpa.com'

    subject = 'Upload Skip Trace Error - Ref# %s' % upload_skip_trace.id
    from_email = settings.DEFAULT_FROM_EMAIL
    to = email_address
    text_content = 'Upload Skip Trace Error'
    html_content = render_to_string(
        'email/email_upload_skip_trace_error.html',
        {'upload_skip_trace': upload_skip_trace},
    )
    email = EmailMultiAlternatives(subject, text_content, from_email, [to])
    email.attach_alternative(html_content, "text/html")
    email.send()


@shared_task
def send_push_to_campaign_confirmation_task(upload_skip_trace_id):
    """
    Alerts user that push to campaign is complete
    """
    upload_skip_trace = UploadSkipTrace.objects.get(id=upload_skip_trace_id)
    rep = upload_skip_trace.created_by
    email_address = rep.email

    try:
        # Save counts here - in case slow this a good place for these queries
        mobile_phone_count = CampaignProspect.objects.filter(
            from_upload_skip_trace=upload_skip_trace,
            phone_type='mobile',
        ).count()
        landline_phone_count = CampaignProspect.objects.filter(
            from_upload_skip_trace=upload_skip_trace,
            phone_type='landline',
        ).count()
        dnc_count = CampaignProspect.objects.filter(
            from_upload_skip_trace=upload_skip_trace,
            prospect__do_not_call=True,
        ).count()
        litigator_count = CampaignProspect.objects.filter(
            from_upload_skip_trace=upload_skip_trace,
            is_litigator=True,
        ).count()

        upload_skip_trace.push_to_campaign_mobile_phone_count = mobile_phone_count
        upload_skip_trace.push_to_campaign_landline_phone_count = landline_phone_count
        upload_skip_trace.push_to_campaign_dnc_count = dnc_count
        upload_skip_trace.push_to_campaign_litigator_count = litigator_count
        upload_skip_trace.save(
            update_fields=[
                'push_to_campaign_mobile_phone_count',
                'push_to_campaign_landline_phone_count',
                'push_to_campaign_dnc_count',
                'push_to_campaign_litigator_count',
            ],
        )

    except:  # noqa:E722
        pass

    if email_address and not upload_skip_trace.push_to_campaign_email_confirmation_sent:
        site = Site.objects.get(id=settings.DJOSER_SITE_ID)
        subject = 'Skip Trace Push To Campaign Complete - Ref# %s' % upload_skip_trace.id
        from_email = settings.DEFAULT_FROM_EMAIL
        to = email_address
        text_content = 'Skip Trace Push To Campaign Complete'
        html_content = render_to_string(
            'email/email_push_to_campaign_complete.html',
            {'upload_skip_trace': upload_skip_trace, 'rep': rep, 'site': site},
        )

        email = EmailMultiAlternatives(subject, text_content, from_email, [to])

        email.attach_alternative(html_content, "text/html")

        email.send()

        upload_skip_trace.push_to_campaign_email_confirmation_sent = True
        upload_skip_trace.save(update_fields=['push_to_campaign_email_confirmation_sent'])


def skip_trace_push_to_campaign_task_initial_stage(
        upload_skip_trace: UploadSkipTrace,
        campaign: Campaign,
):
    # On this stage we set some basic values for a running push to campaign task
    if not upload_skip_trace.push_to_campaign_start:
        upload_skip_trace.push_to_campaign_start = django_tz.now()
        upload_skip_trace.save(update_fields=['push_to_campaign_start'])

    if not upload_skip_trace.push_to_campaign_campaign_name:
        upload_skip_trace.push_to_campaign_campaign_name = campaign.name

    upload_skip_trace.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.RUNNING
    upload_skip_trace.save(
        update_fields=[
            'push_to_campaign_status',
            'push_to_campaign_campaign_name',
        ],
    )


def skip_trace_push_to_campaign_task_creating_properties_stage(upload_skip_trace: UploadSkipTrace):
    # If there's no `Prospect`s, create them. This handles legacy uploads that don't have
    # `Prospects` already created.
    create_prospect_count = 0
    skip_trace_properties = SkipTraceProperty.objects.filter(upload_skip_trace=upload_skip_trace)
    # Multiply by 6 because each property can have up to 3 Prospects. Double this so we don't
    # hit 100% during this step. This helps the progress tracker on the frontend make sense.
    upload_skip_trace.total_rows_push_to_campaign = len(skip_trace_properties) * 6
    upload_skip_trace.save(update_fields=['total_rows_push_to_campaign'])

    # We skip any SkipTraceProperty already assigned to the skip trace upload instance
    already_assigned_props = SkipTraceProperty.objects.filter(
        upload_skip_trace=upload_skip_trace,
        prop__upload_skip_trace=upload_skip_trace,
    )
    if already_assigned_props.exists():
        create_prospect_count = already_assigned_props.count()
        upload_skip_trace.last_row_push_to_campaign = create_prospect_count
        skip_trace_properties = skip_trace_properties.difference(already_assigned_props)

    for skip_trace_property in skip_trace_properties:
        Prospect.objects.create_from_skip_trace_property(skip_trace_property)
        create_prospect_count += 1
        upload_skip_trace.last_row_push_to_campaign = create_prospect_count
        upload_skip_trace.save(update_fields=['last_row_push_to_campaign'])


def skip_trace_push_to_campaign_task_push_to_campaign_stage(
        upload_skip_trace: UploadSkipTrace,
        campaign: Campaign,
        tags,
):
    import_type = upload_skip_trace.push_to_campaign_import_type
    prospects = Prospect.objects.filter(prop__upload_skip_trace=upload_skip_trace)

    # If we are only importing new `Prospect`s, exclude the ones already existing.
    if import_type == 'new':
        prospects = prospects.exclude(upload_duplicate=True)

    total_rows_push_to_campaign = len(prospects)
    upload_skip_trace.total_rows_push_to_campaign = total_rows_push_to_campaign
    upload_skip_trace.save(update_fields=['total_rows_push_to_campaign'])

    # We skip any prospect already pushed to this campaign
    already_pushed_prospects = prospects.filter(campaignprospect__campaign=campaign)
    prospects = prospects.difference(already_pushed_prospects)
    # Set processed rows and total to charge according to the skipped prospects
    row_count = already_pushed_prospects.count()
    total_to_charge = already_pushed_prospects.exclude(
        upload_duplicate=True,
    ).filter(campaignprospect__include_in_upload_count=True).count()

    # Loop through each skip trace property and create the prospects for the campaign.
    for prospect in prospects:
        # We check from the DB if we need to stop the task
        stop_check = UploadSkipTrace.objects.filter(
            id=upload_skip_trace.pk,
        ).values("stop_push_to_campaign", "push_to_campaign_status").first()
        if stop_check["stop_push_to_campaign"]:
            if stop_check["push_to_campaign_status"] != UploadSkipTrace.PushToCampaignStatus.AUTO_STOP:  # noqa: E501
                upload_skip_trace.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.PAUSED  # noqa: E501
                upload_skip_trace.stop_push_to_campaign = False
                upload_skip_trace.save(
                    update_fields=['push_to_campaign_status', 'stop_push_to_campaign'],
                )
            break

        row_count += 1
        upload_skip_trace.last_row_push_to_campaign = row_count
        upload_skip_trace.save(
            update_fields=[
                'last_row_push_to_campaign',
            ],
        )
        total_to_charge += push_to_campaign(
            campaign,
            prospect,
            tags=tags,
            upload_skip_trace=upload_skip_trace,
        )

    if total_rows_push_to_campaign != row_count:
        # If this happens, we broke off the loop because we were manually stopped/paused
        return

    upload_skip_trace.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.COMPLETE
    upload_skip_trace.stop_push_to_campaign = False
    upload_skip_trace.last_row_push_to_campaign = total_rows_push_to_campaign
    upload_skip_trace.push_to_campaign_end = django_tz.now()
    if upload_skip_trace.push_to_campaign_transaction:
        upload_skip_trace.charge_push_to_campaign_transaction(total_to_charge)

    upload_skip_trace.save(
        update_fields=[
            'push_to_campaign_status',
            'stop_push_to_campaign',
            'push_to_campaign_campaign_name',
            'last_row_push_to_campaign',
            'push_to_campaign_end',
        ],
    )
    send_push_to_campaign_confirmation_task.delay(upload_skip_trace.pk)


@shared_task
def skip_trace_push_to_campaign_task(upload_skip_trace_id, tags=None):
    """
    Process to push a skip trace upload to a campaign, creating the prospects with it.
    """
    upload_skip_trace = UploadSkipTrace.objects.get(id=upload_skip_trace_id)
    if upload_skip_trace.push_to_campaign_status == UploadSkipTrace.PushToCampaignStatus.COMPLETE:
        # If the task is already completed there is no need to do anything
        return

    # If task stage is not set, its a new push to campaign task, we set stage to INITIAL
    if not upload_skip_trace.push_to_campaign_stage:
        upload_skip_trace.push_to_campaign_stage = UploadSkipTrace.PushToCampaignStages.INITIAL
        upload_skip_trace.save(update_fields=['push_to_campaign_stage'])

    # Get the main objects we'll need and start the process.
    campaign = Campaign.objects.get(id=upload_skip_trace.push_to_campaign_campaign_id)

    stages = UploadSkipTrace.PushToCampaignStages

    # We skip already completed stages (except initial), we can gracefully recover if interrupted
    try:
        # 'INITIAL' STAGE (this one we should do, even if we are on a later stage)
        skip_trace_push_to_campaign_task_initial_stage(upload_skip_trace, campaign)

        # Set the current stage to the next stage, only if we were actually on the initial stage
        if upload_skip_trace.push_to_campaign_stage == stages.INITIAL:
            upload_skip_trace.push_to_campaign_stage = stages.CREATING_PROPERTIES
            upload_skip_trace.save(update_fields=['push_to_campaign_stage'])

        # 'CREATING_PROPERTIES' STAGE
        if upload_skip_trace.push_to_campaign_stage == stages.CREATING_PROPERTIES:
            skip_trace_push_to_campaign_task_creating_properties_stage(upload_skip_trace)

            # Hand off to the next stage
            upload_skip_trace.push_to_campaign_stage = stages.PUSHING_TO_CAMPAIGN
            upload_skip_trace.save(update_fields=['push_to_campaign_stage'])

        # 'PUSHING_TO_CAMPAIGN' STAGE
        if upload_skip_trace.push_to_campaign_stage == stages.PUSHING_TO_CAMPAIGN:
            skip_trace_push_to_campaign_task_push_to_campaign_stage(
                upload_skip_trace,
                campaign,
                tags,
            )

    except SystemExit:
        upload_skip_trace.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.AUTO_STOP
        upload_skip_trace.stop_push_to_campaign = False
        upload_skip_trace.save(update_fields=[
            "push_to_campaign_status",
            "push_to_campaign_stage",
            "stop_push_to_campaign",
        ])
        skip_trace_push_to_campaign_task.delay(upload_skip_trace_id, tags)
        raise
    except Exception:
        upload_skip_trace.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.ERROR
        upload_skip_trace.stop_push_to_campaign = False
        upload_skip_trace.upload_error = traceback.format_exc()
        upload_skip_trace.save(update_fields=[
            "push_to_campaign_status",
            "push_to_campaign_stage",
            "stop_push_to_campaign",
            "upload_error",
        ])


@shared_task
def start_skip_trace_task(upload_skip_trace_id):
    """
    Update uploaded Skip Trace data.
    """
    from .skiptrace import ProcessSkipTraceUpload
    ProcessSkipTraceUpload(UploadSkipTrace.objects.get(id=upload_skip_trace_id)).start()


@shared_task
def validate_skip_trace_returned_address_task(skip_trace_property_id):
    """
    Validate address during skip trace process.
    """
    skip_trace_property = SkipTraceProperty.objects.get(id=skip_trace_property_id)

    # still use batch process with SS since I have that code
    batch = Batch()
    batch.add(Lookup())
    if skip_trace_property.returned_address_1 and skip_trace_property.returned_city_1 and \
            skip_trace_property.returned_state_1 and skip_trace_property.returned_zip_1:
        batch[0].street = f'{skip_trace_property.returned_address_1}, ' \
                          f'{skip_trace_property.returned_city_1} ' \
                          f'{skip_trace_property.returned_state_1} ' \
                          f'{skip_trace_property.returned_zip_1}'
    elif skip_trace_property.returned_address_1 and skip_trace_property.returned_zip_1:
        batch[0].street = skip_trace_property.returned_address_1
        batch[0].zipcode = skip_trace_property.returned_zip_1
    elif skip_trace_property.returned_address_1 and skip_trace_property.returned_city_1 and \
            skip_trace_property.returned_state_1:
        batch[0].street = skip_trace_property.returned_address_1
        batch[0].city = skip_trace_property.returned_city_1
        batch[0].state = skip_trace_property.returned_state_1
    else:
        # Add a invalid address for lookup to keep counter accurate in case no property address
        batch[0].street = "123 Invalid address"

    try:
        smarty_client.send_batch(batch)
    except SmartyException:
        return

    for i, lookup in enumerate(batch):
        candidates = lookup.result
        if len(candidates) == 0:
            skip_trace_property.validated_returned_property_status = 'invalid'
            skip_trace_property.save(update_fields=['validated_returned_property_status'])
        else:
            candidate = candidates[0]
            components = candidate.components

            skip_trace_property.validated_returned_property_status = 'validated'
            skip_trace_property.validated_returned_address_1 = candidate.delivery_line_1
            skip_trace_property.validated_returned_address_2 = candidate.delivery_line_2
            skip_trace_property.validated_returned_city_1 = components.city_name
            skip_trace_property.validated_returned_state_1 = components.state_abbreviation
            skip_trace_property.validated_returned_zip_1 = components.zipcode

            skip_trace_property.save(update_fields=['validated_returned_property_status',
                                                    'validated_returned_address_1',
                                                    'validated_returned_address_2',
                                                    'validated_returned_city_1',
                                                    'validated_returned_state_1',
                                                    'validated_returned_zip_1'])


@shared_task
def gather_daily_skip_trace_stats(date_str):
    """
    We need to provide daily stats for skip traces to see how much our users are using skip trace
    as well as how much data we're fetching from idi.

    :param date_str string: The date for which we're gathering skip trace data.
    """
    date = parse_date(date_str)
    uploads = UploadSkipTrace.objects.filter(upload_end__date=date).aggregate(
        external_hits=Sum('total_billable_hits') - Sum('total_internal_hits'),
        internal_hits=Sum('total_internal_hits'),
    )
    return SkipTraceDailyStats.objects.update_or_create(
        date=date,
        defaults={
            'total_external_hits': uploads.get('external_hits') or 0,
            'total_internal_hits': uploads.get('internal_hits') or 0,
        },
    )
