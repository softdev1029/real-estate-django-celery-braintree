from datetime import timedelta
import re
import urllib.parse

from celery import shared_task
import requests
from telnyx.error import APIError, InvalidParametersError, InvalidRequestError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction
from django.db.models import F
from django.utils import timezone as django_tz

from campaigns.models import AutoDeadDetection, InitialResponse
from core.utils import clean_phone
from prospects.models import ProspectRelay
from prospects.utils import record_phone_number_opt_outs
from sherpa.models import (
    CampaignProspect,
    Company,
    LeadStage,
    LitigatorReportQueue,
    PhoneNumber,
    SMSMessage,
    SMSTemplate,
)
from .models import SMSResult

User = get_user_model()


@shared_task
def track_sms_reponse_time_task(prospect_id, rep_id):
    """
    Track how long for prospect to respond to sms.
    """

    # Query all messages from this prospect/number that hasn't a response dt set
    sms_message_list = SMSMessage.objects.filter(
        prospect_id=prospect_id,
        response_dt=None,
    )

    now = django_tz.now()
    for sms_message in sms_message_list:
        # For each message that doesn't have a response date we need to set it along with
        # calculating the response time.
        sms_message.response_from_rep_id = rep_id

        sms_message.response_dt = now
        response_time = now - sms_message.dt
        response_seconds = response_time.total_seconds()
        sms_message.response_time_seconds = response_seconds
        sms_message.save(update_fields=[
            'response_from_rep_id', 'response_time_seconds', 'response_dt'])


@shared_task
def sms_message_received_router(from_number, to_number, message, media_url=None):
    """
    Checks if this is a relay from a rep or a message from a prospect and routes accordingly to the
    correct task. Runs when receiving a message webhook from Telnyx.
    """
    to_number_cleaned = clean_phone(to_number)
    from_number_cleaned = clean_phone(from_number)
    # If this message is being sent from an agent relay phone to a relay number, then it is a relay
    # message from a rep. Otherwise, it is a message from a prospect.
    if ProspectRelay.objects.filter(
        relay_number__phone=to_number_cleaned,
        agent_profile__phone=from_number_cleaned,
    ).exists():
        sms_relay_from_rep_task(from_number, to_number, message, media_url=media_url)
    else:
        sms_message_received(from_number, to_number, message, media_url=media_url)


@shared_task
def sms_relay_from_rep_task(from_number, to_number, message, media_url=None):
    """
    Relays message from rep to prospect.
    """
    to_number_cleaned = clean_phone(to_number)
    from_number_cleaned = clean_phone(from_number)

    if not message:
        message = 'no_text'

    relay = ProspectRelay.objects.filter(
        relay_number__phone=to_number_cleaned,
        agent_profile__phone=from_number_cleaned,
    ).first()

    relay.send_from_rep(message, media_url)

    track_sms_reponse_time_task.delay(relay.prospect.id, relay.agent_profile.user.id)


@shared_task  # noqa: C901
def sms_message_received(from_number, to_number, message, num_media=None, file_extension=None,
                         media_url=None):
    """
    Task that is called on all messages that have been received.

    :arg from_number: The fully qualified number that the message was received from.
    :arg to_number: The fully qualified number that the message was sent to.
    :arg message: Text message body message.
    """

    # TODO: refactor this into the short-code handling code for CH14715
    from_number_cleaned = clean_phone(from_number)
    if not from_number_cleaned:
        return

    # ====================== Find company ======================
    to_number_cleaned = clean_phone(to_number)

    try:
        phone_record = PhoneNumber.objects.get(phone=to_number_cleaned)
    except MultipleObjectsReturned:
        phone_record = PhoneNumber.objects.filter(
            phone=to_number_cleaned,
            status=PhoneNumber.Status.ACTIVE,
        ).last()

        # There's still a chance that the phone number was not found, if there are multiple released
        # numbers, but no active.
        if not phone_record:
            phone_record = PhoneNumber.objects.filter(phone=to_number_cleaned).last()
    except PhoneNumber.DoesNotExist:
        # Received a message to a number that we have in twilio, however it's not in sherpa.
        # TODO (aww20191016) should log this as it seems the number should be released in twilio.
        return

    company = phone_record.company

    # ====================== Find prospect ======================

    # lean on default ordering of prospects by pk to get last for company w that number
    prospect = company.prospect_set.filter(phone_raw=from_number_cleaned).last()

    if not prospect or prospect.is_blocked:
        return

    # ====================== Find CampaignProspects ======================

    campaign_prospect_list = CampaignProspect.objects.filter(prospect=prospect)

    if len(campaign_prospect_list) == 0:
        # Log as an error
        return

    # === Identity if should check for Dead(Auto) if is first message received for prospect ====

    check_dead_auto = False

    if prospect.has_responded_via_sms != 'yes':
        for cp in campaign_prospect_list:
            # if any campaign has set_auto_dead true then check_dead_auto
            company_auto_dead = cp.campaign.company.auto_dead_enabled
            campaign_auto_dead = cp.campaign.set_auto_dead
            auto_dead = company_auto_dead if company_auto_dead is not None else campaign_auto_dead
            if auto_dead:
                check_dead_auto = True
                break

    # Check for wrong number
    wrong_number_list = ['wrong number', 'wrong person']
    if any(phrase in message.lower() for phrase in wrong_number_list):
        prospect.toggle_wrong_number(value=True)

    # ====================== Check if has Dead(Auto) word if check_dead_auto ======================

    set_auto_dead = False

    if not message:
        message = 'no_text'
    else:
        # identity if has_auto_dead_word in message
        if check_dead_auto:
            try:
                # Store results of the auto detection service.
                if not settings.TEST_MODE:
                    encoded_message = urllib.parse.quote(message)
                    url = f'{settings.PROSPECT_SERVICE_URL}dnc?q={encoded_message}'
                    response = requests.get(url)
                    score = response.json().get('dnc_score')

                    # Record the auto_dead decision.
                    AutoDeadDetection.objects.create(
                        message=message,
                        marked_auto_dead=score >= 0.85,
                        score=score,
                    )
            except:  # noqa: E722
                # Should always pass regardless of any error for now.
                pass

            auto_dead_words_list = [
                "no",
                "nope",
                "lose",
                "sold",
                "off",
                "dont",
                "stop",
                "sorry",
                "remove",
                "not",
                "sorry",
                "alone",
                "fuck",
                "spam",
                "never",
                "quit",
                "end",
                "unsubscribe",
                "removeme",
                "fuckyou",
                "spammer",
                "spam",
                "unsub",
            ]
            message_to_check = re.sub(r"[^\w\d\s]+", '', message)
            message_to_check = message_to_check.lower().split()
            if any(word in message_to_check for word in auto_dead_words_list):
                set_auto_dead = True

    # ====================== Create litigator report queue ======================

        prospect_reply_words_list = [
            "report",
            "reported",
            "reporting",
            "scam",
            "scamming",
            "illegal",
            "violation",
            "DNC registry",
            "Do Not Contact List",
            "National Do Not Contact",
            "National DNC",
        ]
        for word in prospect_reply_words_list:
            result = re.findall('\\b' + word + '\\b', message, flags=re.IGNORECASE)
            if len(result) > 0:
                LitigatorReportQueue.submit(prospect)
                break

    # ====================== Create SMSMessage in Sherpa ======================

    if file_extension == 'na':
        file_extension = ''

    if media_url == 'na':
        media_url = ''

    stop_called = message.lower() == 'stop' and company.auto_filter_messages

    if set_auto_dead or stop_called:
        unread_by_recipient = False
    else:
        unread_by_recipient = True

    to_number_cleaned = clean_phone(to_number)
    our_number = "+1%s" % to_number_cleaned
    contact_number = "+1%s" % from_number_cleaned

    sms_message = SMSMessage.objects.create(
        our_number=our_number,
        contact_number=contact_number,
        from_number=contact_number,
        to_number=our_number,
        message=message,
        prospect=prospect,
        unread_by_recipient=unread_by_recipient,
        company=prospect.company,
        num_media=num_media,
        media_url=media_url,
        file_extension=file_extension,
        from_prospect=True,
    )

    # ====================== Update Prospects, CampaignProspects, Campaign ======================

    # Get the appropriate lead stage depending on if an auto dead was detected.
    if set_auto_dead or stop_called:
        lead_stage = LeadStage.objects.get(lead_stage_title="Dead (Auto)", company=company)
    else:
        lead_stage = LeadStage.objects.get(lead_stage_title="Response Received", company=company)

    if not prospect.lead_stage or prospect.lead_stage.lead_stage_title == 'Initial Message Sent':
        prospect.lead_stage = lead_stage
    prospect.has_responded_via_sms = 'yes'

    # Determine if the message is turning the prospect to unread.
    is_new_unread = not prospect.has_unread_sms
    if set_auto_dead or stop_called:
        prospect.toggle_autodead(True)
        prospect.do_not_call = True
    else:
        prospect.has_unread_sms = True

    # Lock the prospect so that we avoid race conditions of incrementing unread.
    with transaction.atomic():
        if is_new_unread:
            prospect.modify_unread_count(1)
        prospect.last_sms_received_utc = django_tz.now()
        prospect.save(
            update_fields=[
                'lead_stage',
                'has_responded_via_sms',
                'do_not_call',
                'has_unread_sms',
                'last_sms_received_utc',
            ],
        )

    # campaign_id_list is a hack to make sure only check and add stats to a campaign once
    campaign_id_list = []

    for campaign_prospect in campaign_prospect_list:

        campaign_prospect.has_responded2 = True
        if set_auto_dead or stop_called:
            campaign_prospect.has_responded_dead_auto2 = True

        campaign_prospect.save(update_fields=['has_responded2', 'has_responded_dead_auto2'])

        if campaign_prospect.has_responded_via_sms != 'yes':
            # Track the initial response from the campaign prospect.
            try:
                InitialResponse.objects.create(
                    campaign=campaign_prospect.campaign,
                    message=sms_message,
                    is_auto_dead=set_auto_dead or stop_called,
                )
            except Exception:
                # Sometimes it attempts to create a duplicate. If this happens, just continue.
                pass

            campaign_prospect.has_responded_via_sms = 'yes'

        if not set_auto_dead and not stop_called:
            campaign_prospect.has_unread_sms = True

        campaign_prospect.save(update_fields=['has_responded_via_sms',
                                              'has_unread_sms'])

        campaign = campaign_prospect.campaign
        if campaign.id not in campaign_id_list:
            stats = campaign.campaign_stats
            stats.total_sms_received_count = stats.total_sms_received_count + 1
            update_fields_stats = ['total_sms_received_count']
            if set_auto_dead or stop_called:
                stats.total_auto_dead_count = stats.total_auto_dead_count + 1
                update_fields_stats.append('total_auto_dead_count')
            else:
                campaign.has_unread_sms = True
            stats.save(update_fields=update_fields_stats)
            campaign.save(update_fields=['has_unread_sms'])

            campaign_id_list.append(campaign.id)

        sms_message.market = campaign.market
        sms_message.save(update_fields=['market'])

    # ==== Check if this message should be "relayed" to rep =====
    if prospect.relay:
        try:
            prospect.relay.send(message, media_url)
        except (APIError, InvalidParametersError, InvalidRequestError):
            # Received an error from telnyx, typically seen with blocked carriers.
            pass

    # ==== Record stats with other tasks =====
    # Record received to stats
    record_phone_number_stats_received.delay(our_number)

    # Record auto-dead stats
    if set_auto_dead or stop_called:
        record_phone_number_auto_dead.delay(our_number)

    if stop_called:
        record_phone_number_opt_outs(from_number_cleaned, to_number_cleaned)


@shared_task
def record_phone_number_stats_received(phone_number):
    """
    TODO: This isn't actually a task. It's only called in `sms_message_received` and could be moved
    out into synchronous code.
    """
    phone_number = clean_phone(phone_number)
    phone_record = PhoneNumber.objects.filter(
        phone=phone_number,
    ).exclude(status=PhoneNumber.Status.RELEASED).first()
    if not phone_record:
        # The phone number that received the message does not exist.
        return

    now = django_tz.now()
    phone_record.last_received_utc = now
    phone_record.save(update_fields=['last_received_utc'])


@shared_task
def record_phone_number_auto_dead(phone_number):
    """
    Aggregates a field on the phone record if auto dead was received.

    TODO: This isn't actually a task. Only called in `sms_message_received` and can be moved into
    synchronous code.
    """
    phone_number = clean_phone(phone_number)
    phone_record = PhoneNumber.objects.filter(
        phone=phone_number,
        status=PhoneNumber.Status.ACTIVE,
    ).first()
    if not phone_record:
        # The phone number that received the message does not exist.
        return

    # Add to total count
    phone_record.total_auto_dead = phone_record.total_auto_dead + 1
    phone_record.save(update_fields=['total_auto_dead'])


@shared_task  # noqa: C901
def telnyx_status_callback_task(provider_message_id, message_status, error_code):
    """
    Receive the payload sent by telnyx and process the status response.
    """
    try:
        sms_message = SMSMessage.objects.get(provider_message_id=provider_message_id)
    except SMSMessage.DoesNotExist:
        # There are a rare instances when the sms message does not exist in our system.
        return

    phone_raw = clean_phone(sms_message.from_number)
    try:
        phone_record = PhoneNumber.objects.get(phone=phone_raw)
    except PhoneNumber.MultipleObjectsReturned:
        # There are some cases where multiple phone numbers exist, usually with 1 active and 1
        # released. There can't be multiple active, otherwise we have an actual issue.
        phone_records = PhoneNumber.objects.filter(
            phone=phone_raw,
            status__in=[
                PhoneNumber.Status.ACTIVE,
                PhoneNumber.Status.INACTIVE,
            ],
        ).order_by('status')

        if not phone_records.exists():
            # None of the numbers found from before are active or inactive.
            return

        # In the event we somehow have an active and inactive number, we'll grab the active one.
        # This shouldn't ever happen though.
        phone_record = phone_records.first()
    except PhoneNumber.DoesNotExist:
        # There is no Sherpa number with this phone number
        return

    phone_record.record_sent()

    # Create/Update the result object and save sms status.
    result, created = SMSResult.objects.get_or_create(
        sms=sms_message,
        defaults={
            'error_code': error_code,
            'status': message_status,
        },
    )

    if not created:
        result.status = message_status
        result.save(update_fields=['status'])

    # Update batch stats when message becomes delivered.
    if message_status == 'delivered':
        sms_message.message_status = 'delivered'
        sms_message.save(update_fields=['message_status'])
        stats_batch = sms_message.stats_batch

        # Message is sent either invidividually to the prospect, or part of a campaign batch.
        if stats_batch:
            delivered_count = stats_batch.messages.filter(message_status='delivered').count()
            stats_batch.delivered = delivered_count
            stats_batch.save(update_fields=['delivered'])

            # Update the delivered count on the campaign.
            campaign = stats_batch.campaign
            campaign_stats = campaign.campaign_stats
            campaign_stats.has_delivered_sms_only_count = F('has_delivered_sms_only_count') + 1
            campaign_stats.save(update_fields=['has_delivered_sms_only_count'])

    # Update campaign related status if this is a bulk message.
    if sms_message.is_bulk_message:
        sms_message.update_cp_stats(message_status, error_code)

    # Check the current message stats batch to determine if the majority of results resulted in
    # spam.
    if error_code == '40002' and sms_message.stats_batch:
        verify_spam_counts.delay(sms_message.stats_batch_id)


@shared_task
def update_template_stats():
    """
    Goes through all active templates for active subcription companies and updates their delivery
    percent and response rate.
    """
    companies = Company.objects.filter(
        subscription_status__in=[
            Company.SubscriptionStatus.ACTIVE,
            Company.SubscriptionStatus.PAST_DUE,
        ],
    )
    for template in SMSTemplate.objects.filter(company__in=companies, is_active=True):
        template.delivery_percent = template.get_delivery_percent()
        # TODO: `get_response_rate()` is too slow right now, from the "stop" filter.
        template.response_rate = template.get_response_rate()
        template.save()


@shared_task
def verify_spam_counts(stats_batch_id):
    """
    Determines if enough messages within a StatsBatch resulted in spam (40002 result) which will
    force a cooldown period of the market.
    """
    results = SMSResult.objects.filter(sms__stats_batch_id=stats_batch_id)
    if results.count() < 65:
        # Not enough results have been provided.
        return

    if results.filter(error_code='40002').count() < 40:
        # Not enough spam messages in the batch.
        return

    # Enough spam results have been saved.  Begin cooldown period.
    market = results.first().sms.market
    market.current_spam_cooldown_period_end = django_tz.now() + timedelta(hours=2)
    market.save(update_fields=['current_spam_cooldown_period_end'])
