from datetime import date, timedelta

from celery import shared_task
from telnyx.error import APIError, InvalidRequestError, PermissionError
from twilio.base.exceptions import TwilioRestException

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.db.models import F, Q
from django.utils import timezone as django_tz
from django.utils.dateparse import parse_date

from phone.choices import Provider
from prospects.utils import record_phone_number_opt_outs
from sherpa.models import (
    Activity,
    Campaign,
    CampaignProspect,
    Company,
    Prospect,
    ReceiptSmsDirect,
    SMSMessage,
    SMSTemplate,
    StatsBatch,
)
from sherpa.tasks import sherpa_send_email
from sms.models import SMSResult
from sms.utils import telnyx_error_has_error_code
from .directmail_clients import DirectMailOrderStatus
from .models import CampaignDailyStats, DirectMailCampaign, DirectMailOrder
from .utils import get_target_hours

User = get_user_model()


@shared_task  # noqa: C901
def attempt_batch_text(campaign_prospect_id, sms_template_id, sent_by_user_id, force_skip=False):
    """
    Attempt to send a message to a user through batch send.

    This is called when a user goes through their bulk send and sends a lot of messages. The message
    isn't actually always sent, sometimes the message can be skipped for a variety of reasons.
    """
    campaign_prospect = CampaignProspect.objects.get(id=campaign_prospect_id)
    if not campaign_prospect.is_valid_send:
        return
    campaign = campaign_prospect.campaign
    prospect = campaign_prospect.prospect
    phone_type = prospect.phone_data
    company = prospect.company
    initial_message_sent_by_rep = User.objects.get(id=sent_by_user_id)
    market = campaign.market

    # Save stats_batch to campaign_prospect here
    stats_batch = campaign.update_stats_batch()
    campaign_prospect.stats_batch = stats_batch
    campaign_prospect.save(update_fields=['stats_batch'])

    if campaign is not None:
        stats = campaign.campaign_stats
        stats.total_sms_followups = F('total_sms_followups') + 1
        stats.save(update_fields=['total_sms_followups'])

    if phone_type and phone_type.should_lookup_carrier:
        phone_type.lookup_phone_type()

    sms_template = SMSTemplate.objects.get(id=sms_template_id)
    campaign_prospect.sms_template = sms_template
    campaign_prospect.save(update_fields=['sms_template'])

    if company.use_sender_name:
        sender_name = initial_message_sent_by_rep.first_name
    else:
        sender_name = company.outgoing_user_names[0]

    message_formatted = prospect.build_bulk_message(
        sms_template,
        sender_name=sender_name,
        campaign=campaign,
    )

    # We should have a formatted message by this point
    if campaign_prospect.check_skip(force_skip=force_skip):
        campaign.campaign_stats.total_skipped = F('total_skipped') + 1
        campaign.campaign_stats.save(update_fields=['total_skipped'])
        return

    campaign_prospect.prospect.set_lead_stage()

    # ====== create sms receipt =======
    ReceiptSmsDirect.objects.create(
        phone_raw=prospect.phone_raw,
        campaign=campaign,
        company=company,
    )

    if campaign.call_forward_number:
        prospect.call_forward_number = campaign.call_forward_number
        prospect.save(update_fields=['call_forward_number'])

    sherpa_phone_number = campaign_prospect.assign_number()

    if sherpa_phone_number and message_formatted:
        sherpa_phone_twilio = f'+1{sherpa_phone_number.phone}'
        message = message_formatted
        client = sherpa_phone_number.client
        prospect_full_number = prospect.full_number
        sms_message = SMSMessage.objects.create(
            our_number=sherpa_phone_twilio,
            contact_number=prospect_full_number,
            from_number=sherpa_phone_twilio,
            to_number=prospect_full_number,
            message=message,
            prospect=prospect,
            company=company,
            initial_message_sent_by_rep=initial_message_sent_by_rep,
            campaign=campaign,
            market=market,
            stats_batch=stats_batch,
            template=sms_template,
        )

        error_code = None
        try:
            message_response = client.send_message(
                to=prospect_full_number,
                from_=sherpa_phone_twilio,
                body=message,
            )
            # TODO: We need to redesign this
            provider = sherpa_phone_number.provider
            if provider == Provider.TELNYX:
                sms_message.provider_message_id = message_response.id
                sms_message.message_status = message_response.to[0].get('status')
            elif provider == Provider.TWILIO:
                sms_message.provider_message_id = message_response.sid
                sms_message.message_status = message_response.status
            elif provider == Provider.INTELIQUENT:
                sms_message.provider_message_id = message_response.get('sid')
                sms_message.message_status = message_response.get('status')
            sms_message.save(update_fields=['provider_message_id', 'message_status'])
        except (InvalidRequestError, APIError, PermissionError) as e:

            # There are a few error codes that come up from the `InvalidRequestError`
            error_data = e.json_body.get('errors')
            if not error_data:
                error_code = ''
            else:
                error_code = error_data[0].get('code', '')

            # We make sure to update opted_out, even if there are other errors
            if telnyx_error_has_error_code(e, '40300'):
                # Stop rule triggered.
                record_phone_number_opt_outs(prospect.phone_raw, sherpa_phone_number.phone)

        except TwilioRestException as e:
            error_code = str(e.code)

            if error_code == "30007":
                campaign_prospect.set_skip_reason(CampaignProspect.SkipReason.CARRIER)
                campaign.campaign_stats.total_skipped = F('total_skipped') + 1
                campaign.campaign_stats.save(update_fields=['total_skipped'])

        if not campaign_prospect.skipped and error_code is not None:
            return SMSResult.objects.create(
                sms=sms_message,
                error_code=error_code,
                status=SMSResult.Status.SENDING_FAILED,
            )

        sherpa_phone_number.last_send_utc = django_tz.now()
        sherpa_phone_number.save(update_fields=['last_send_utc'])

        campaign_prospect.update_bulk_sent_stats()
    else:
        campaign_prospect.sms_status = 'failure6'
        campaign_prospect.save(update_fields=['sms_status'])


@shared_task
def update_total_initial_sent_skipped_task(campaign_id):
    """
    Manually called task to update the initial sent or skipped messages
    """
    campaign = Campaign.objects.get(id=campaign_id)

    total_initial_sent_skipped_count = CampaignProspect.objects.filter(
        Q(sent=True) | Q(skipped=True),
        campaign=campaign,
        prospect__phone_type='mobile',
    ).count()

    if campaign.campaign_stats.total_initial_sent_skipped != total_initial_sent_skipped_count:
        campaign.campaign_stats.total_initial_sent_skipped = total_initial_sent_skipped_count
        campaign.campaign_stats.save(update_fields=['total_initial_sent_skipped'])


@shared_task  # noqa: C901
def transfer_campaign_prospects(old_campaign_id, new_campaign_id, filters=None):
    """
    Transfers certain prospects from the original campaign to the followup campaign.

    - reset many of the fields for the followup campaign
    - update aggregated field stats for the old campaign
    """
    old_campaign = Campaign.objects.get(id=old_campaign_id)
    new_campaign = Campaign.objects.get(id=new_campaign_id)

    # Transfer certain campaign prospects to the new campaign.
    campaign_prospect_list = CampaignProspect.objects.filter(campaign=old_campaign)
    reset_skipped = False
    if filters:
        lead_stage_filter = Q()
        responded_filter = Q()
        prospects_filter = Q()
        skip_reason_filter = Q()
        keyword_filter = Q()

        if 'responded' in filters:
            if filters['responded']:
                responded_filter |= Q(has_responded_via_sms='yes')
            elif filters['responded'] is False:
                # If filtering by has "not responded" then we need to take either 'no' or empty str.
                responded_filter |= ~Q(has_responded_via_sms='yes')

        if 'priority' in filters:
            prospects_filter |= Q(prospect__is_priority=filters['priority'])

        if 'dnc' in filters:
            prospects_filter |= Q(prospect__do_not_call=filters['dnc'])

        if 'verified' in filters:
            prospects_filter |= Q(
                prospect__owner_verified_status=Prospect.OwnerVerifiedStatus.VERIFIED,
            )

        if 'non_owner' in filters:
            prospects_filter |= Q(
                prospect__owner_verified_status=Prospect.OwnerVerifiedStatus.UNVERIFIED,
            )

        if 'qualified' in filters:
            prospects_filter |= Q(prospect__is_qualified_lead=filters['qualified'])

        if 'skip_reason' in filters:
            reset_skipped = True
            if filters['skip_reason'] == 'any':
                skip_reason_filter |= Q(skipped=True)
            else:
                if filters['skip_reason'] == CampaignProspect.SkipReason.CARRIER:
                    carrier_skips = [
                        CampaignProspect.SkipReason.CARRIER,
                        CampaignProspect.SkipReason.ATT,
                        CampaignProspect.SkipReason.VERIZON,
                    ]
                    skip_reason_filter |= Q(skip_reason__in=carrier_skips)
                else:
                    skip_reason_filter |= Q(skip_reason=filters['skip_reason'])
        else:
            skip_reason_filter |= Q(sent=True)

        if 'lead_stage' in filters:
            for lead_id in filters['lead_stage']:
                lead_stage_filter |= Q(prospect__lead_stage_id=lead_id)

        if 'message_search' in filters:
            for message in filters['message_search']:
                keyword_filter |= Q(prospect__messages__message__icontains=message.lower())

        query_filters = Q(lead_stage_filter & responded_filter & prospects_filter & skip_reason_filter & keyword_filter)  # noqa: E501
        campaign_prospect_list = campaign_prospect_list.filter(query_filters)
    else:
        # To maintain compatibility with legacy, we need to filter to only sent and not responded
        # as the default filter.
        campaign_prospect_list = campaign_prospect_list.filter(
            ~Q(has_responded_via_sms='yes'),
            sent=True,
        )

    # Only transfer `mobile` Prospects.
    campaign_prospect_list = campaign_prospect_list.filter(
        prospect__phone_type=Prospect.PhoneType.MOBILE,
    )

    for campaign_prospect in campaign_prospect_list:
        campaign_prospect.transfer(new_campaign, reset_skipped=reset_skipped)

    # Certain fields are affected by the save hook, and need to be set after transfering the cps
    new_campaign.update_has_priority()
    update_total_initial_sent_skipped_task.delay(new_campaign_id)
    update_total_qualified_leads_count_task.delay(new_campaign_id)
    update_total_mobile_count_task.delay(new_campaign_id)
    record_skipped_send.delay(new_campaign_id)

    # Update certain aggregated fields in the original campaign, which are changed after the
    # campaign prospects have been transfered.
    old_campaign.update_has_priority()
    update_total_initial_sent_skipped_task.delay(old_campaign_id)
    update_total_qualified_leads_count_task.delay(old_campaign_id)
    update_total_mobile_count_task.delay(old_campaign_id)
    record_skipped_send.delay(old_campaign_id)


@shared_task
def update_total_qualified_leads_count_task(campaign_id):
    """
    Manually called task to update the count of qualified leads on a campaign.
    """
    campaign = Campaign.objects.get(id=campaign_id)
    qualified_lead_count = campaign.total_leads_generated

    if campaign.campaign_stats.total_leads != qualified_lead_count:
        campaign.campaign_stats.total_leads = qualified_lead_count
        campaign.campaign_stats.save(update_fields=['total_leads'])


@shared_task
def update_total_mobile_count_task(campaign_id):
    """
    Manually called task to update mobile phone count for a campaign.
    """
    campaign = Campaign.objects.get(id=campaign_id)
    mobile_count = campaign.campaignprospect_set.filter(prospect__phone_type='mobile').count()
    if campaign.campaign_stats.total_mobile != mobile_count:
        campaign.campaign_stats.total_mobile = mobile_count
        campaign.campaign_stats.save(update_fields=['total_mobile'])


@shared_task
def record_skipped_send(campaign_prospect_id):
    """
    Records that a message has been skipped.
    """
    try:
        campaign_prospect = CampaignProspect.objects.get(id=campaign_prospect_id)
    except CampaignProspect.DoesNotExist:
        # Sometimes we see with very old campaign prospects that they no longer exist.
        return

    campaign = campaign_prospect.campaign
    count = CampaignProspect.objects.filter(campaign=campaign, skipped=True).count()
    campaign.campaign_stats.total_skipped = count
    campaign.campaign_stats.save(update_fields=['total_skipped'])


@shared_task
def recalculate_stats(campaign_id: int):
    # This will go to all statsbatches and recalculate skipped, delivered and sent stats
    # Finally it will recalculate the campaign stats based on the new statsbatch values
    campaign = Campaign.objects.get(id=campaign_id)
    batches = StatsBatch.objects.filter(campaign=campaign)
    total_sent = 0
    total_sent_attempted = 0
    total_delivered = 0
    total_skipped = 0

    for batch in batches:
        delivered_sms_count = SMSMessage.objects.filter(
            stats_batch=batch,
            message_status='delivered',
        ).distinct("prospect").count()
        skipped_sms_count = CampaignProspect.objects.filter(
            stats_batch=batch,
            skipped=True,
        ).count()
        sent_sms_count = CampaignProspect.objects.filter(
            stats_batch=batch,
            sent=True,
        ).count()
        sent_attempt_count = CampaignProspect.objects.filter(stats_batch=batch).count()

        batch.sent = sent_sms_count
        batch.send_attempt = sent_attempt_count
        batch.delivered = delivered_sms_count
        if batch.delivered > batch.send_attempt - skipped_sms_count:
            # If this happens, most likely the CampaignProspect got deleted
            batch.send_attempt = batch.delivered + skipped_sms_count
        batch.save(update_fields=["sent", "send_attempt", "delivered"])

        total_sent += sent_sms_count
        total_sent_attempted += sent_attempt_count
        total_delivered += delivered_sms_count
        total_skipped += skipped_sms_count

    campaign_stats = campaign.campaign_stats
    campaign_stats.total_skipped = total_skipped
    campaign_stats.total_sms_sent_count = total_sent
    campaign_stats.save(update_fields=["total_skipped", "total_sms_sent_count"])

    campaign.total_skipped = total_skipped
    campaign.total_sms_sent_count = total_sent
    campaign.save(update_fields=["total_skipped", "total_sms_sent_count"])


@shared_task
def modify_campaign_daily_stats(campaign_id, date_str):
    """
    Either create or update the daily stats for a given campaign and date.
    """
    campaign = Campaign.objects.get(id=campaign_id)
    date = parse_date(date_str)

    # Generate the stats for the campaign on this day.
    sent_count = campaign.get_bulk_sent_messages(start_date=date, end_date=date).count()
    new_lead_count = campaign.get_prospect_activities(
        start_date=date,
        end_date=date,
        activity_title=Activity.Title.ADDED_QUALIFIED,
    ).count()
    auto_dead_count = campaign.get_prospect_activities(
        start_date=date,
        end_date=date,
        activity_title=Activity.Title.ADDED_AUTODEAD,
    ).count()
    response_count = campaign.get_responses(start_date=date, end_date=date).count()
    delivered_count = campaign.get_delivered_initial_messages(
        start_date=date,
        end_date=date,
    ).count()
    skipped_count = campaign.get_skipped_count(start_date=date, end_date=date)

    # Create or modify the the `CampaignDailyStats` instance.
    instance, _ = CampaignDailyStats.objects.update_or_create(
        campaign=campaign,
        date=date,
        defaults={
            'new_leads': new_lead_count,
            'sent': sent_count,
            'auto_dead': auto_dead_count,
            'responses': response_count,
            'delivered': delivered_count,
            'skipped': skipped_count,
        },
    )
    return instance


@shared_task
def set_daily_campaign_stats(date_str):
    """
    Set all the campaign stats for the day for active campaigns.
    """
    companies = Company.objects.filter(subscription_status__in=['active', 'past_due'])
    for company in companies:
        campaigns = company.campaign_set.filter(is_archived=False)
        for campaign in campaigns:
            modify_campaign_daily_stats(campaign.id, date_str)


@shared_task
def send_dm_lock_remainder_email():
    """
    Send warning mail to lock the DM campaign before 5 days
    from drop date.
    """
    try:
        current_date = django_tz.now()
        check_on_date = (current_date + django_tz.timedelta(days=5)).date()
        todays_remainder = DirectMailOrder.objects.filter(
            drop_date__lte=check_on_date,
            status=DirectMailOrderStatus.SCHEDULED,
        )
        if todays_remainder.exists():
            for an_dm_camp in todays_remainder:
                try:
                    dm_camp = DirectMailCampaign.objects.get(order=an_dm_camp, reminder_sent=False)
                    campaign = dm_camp.campaign
                    site = Site.objects.get(id=settings.DJOSER_SITE_ID)
                    sherpa_send_email(
                        '48 Hour Direct Mail Campaign Deadline Approaching',
                        'email/direct_mail/lock_remainder_mail.html',
                        campaign.created_by.email,
                        {
                            'site': site,
                            'campaign_name': campaign.name,
                            'campaign_id': campaign.id,
                            'drop_date': an_dm_camp.drop_date.strftime('%Y-%m-%d'),
                        },
                    )
                    dm_camp.reminder_sent = True
                    dm_camp.save(update_fields=['reminder_sent'])
                except DirectMailCampaign.DoesNotExist:
                    continue
    except Exception:
        pass


@shared_task
def lock_dm_campaign_n_auth_payment():
    """
    Authorize payment and lock DM campaign for editing 3
    days before drop rate.
    """
    current_date = django_tz.now()
    check_on_date = (current_date + django_tz.timedelta(days=3)).date()
    to_lock_orders = DirectMailOrder.objects.filter(
        drop_date__lte=check_on_date,
        status=DirectMailOrderStatus.SCHEDULED,
    )
    if to_lock_orders.exists():
        for an_dm_camp in to_lock_orders:
            an_dm_camp.auth_and_lock_order()


@shared_task
def charge_locked_dm_campaign():
    """
    Charges Campaign 48 hours before drop date that are locked.
    """
    if settings.DEBUG:
        return

    target_hours = get_target_hours()
    target_drop_date = date.today() + timedelta(hours=target_hours)
    to_charge_orders = DirectMailOrder.objects.filter(
        drop_date__lte=target_drop_date,
        status=DirectMailOrderStatus.LOCKED,
    )
    if to_charge_orders.exists():
        for an_dm_camp in to_charge_orders:
            dm_camp = DirectMailCampaign.objects.get(order=an_dm_camp)
            campaign = dm_camp.campaign

            # We want companies that are billing exempt to work without being charged.
            if not dm_camp.attempt_charge_campaign():
                sherpa_send_email.delay(
                    'Sherpa Direct Mail Transaction Failed',
                    'email/email_direct_email_transaction_failed.html',
                    campaign.created_by.email,
                    {
                        'first_name': campaign.created_by.first_name,
                        'user_full_name': campaign.created_by.get_full_name(),
                        'company_name': campaign.company.name,
                        'campaign_name': campaign.name,
                    },
                )
                an_dm_camp.status = DirectMailOrderStatus.INCOMPLETE
                an_dm_camp.save(update_fields=['status'])
            else:
                dm_camp.push_to_print()


@shared_task
def update_tracking_status():
    """
    Update status for all Direct Mail orders that are processing or out for delivery.
    """
    check_status = [
        DirectMailOrderStatus.PROCESSING,
        DirectMailOrderStatus.IN_PRODUCTION,
        DirectMailOrderStatus.PRODUCTION_COMPLETE,
        DirectMailOrderStatus.OUT_FOR_DELIVERY,
    ]
    orders = DirectMailOrder.objects.filter(status__in=check_status)

    target_hours = get_target_hours(update_status=True)
    target_date = date.today() + timedelta(hours=target_hours)

    for order in orders.exclude(
            status=DirectMailOrderStatus.PROCESSING,
            drop_date__lte=target_date,
    ):
        order.update_status()


@shared_task
def send_campaign_complete_email(campaign_id):
    """
    Sends DM campaign complete email.

    :param user_id int: User ID.
    :param campaign_id int: Campaign ID.
    """
    campaign = Campaign.objects.get(id=campaign_id)
    sherpa_send_email.delay(
        'Sherpa Delivered Campaign Email',
        'email/email_direct_mail_status_delivered_remainder.html',
        campaign.created_by.email,
        {
            'site_id': settings.DJOSER_SITE_ID,
            'campaign_name': campaign.name,
            'campaign_id': campaign.id,
        },
    )


@shared_task
def nightly_directmail_tasks():
    """
    Handles all the nightly DirectMail routines.
    """
    if settings.DEBUG:
        return
    send_dm_lock_remainder_email()
    charge_locked_dm_campaign()
    lock_dm_campaign_n_auth_payment()
    update_tracking_status()
