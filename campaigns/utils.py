from datetime import datetime

from django.db.models import Case, ExpressionWrapper, F, IntegerField, Value, When
from django.db.models.functions import Round
from django.utils import timezone as django_tz

from core.settings.base import (
    DISCOUNT_END_DATE,
    DISCOUNT_START_DATE,
    POST_CARD_DISCOUNT_PRICE,
)
from properties.utils import get_or_create_attom_tags
from sherpa.models import Campaign, CampaignProspect, LitigatorList, Prospect, SiteSettings


def get_campaigns_by_access(user):
    return Campaign.objects.has_access(user).annotate(
        percent=Case(
            When(
                campaign_stats__total_mobile=0,
                then=None,
            ),
            When(
                campaign_stats__total_initial_sent_skipped__gte=F('campaign_stats__total_mobile'),
                then=Value(100.0),
            ),
            When(
                campaign_stats__total_mobile__gt=0,
                then=ExpressionWrapper(
                    Round(Value(1.0) * F('campaign_stats__total_initial_sent_skipped') / F('campaign_stats__total_mobile') * Value(100.0)),  # noqa: E501
                    output_field=IntegerField(),
                ),
            ),
            default=None,
            output_field=IntegerField(),
        ),
    )


def push_to_campaign(campaign, prospect, tags=None, upload_skip_trace=None, sms=True):
    """
    Pushes prospect to specified campaign.

    :param campaign Campaign: Campaign to push to.
    :param prospect Prospect: Prospect being pushed.
    :param upload_skip_trace UploadSkipTrace: UploadSkipTrace object where this prospect was
    created.
    :param tags list: List of tag IDs to add to newly created CampaignProspect.
    :return charge int: Determines if this push should be charged.
    """
    tags = tags or []
    charge = 0
    related = Prospect.objects.filter(related_record_id=prospect.related_record_id)
    related_phones = related.values('phone_raw')
    has_litigator_list = LitigatorList.objects.filter(phone__in=related_phones)
    sort_order = CampaignProspect.objects.filter(
        prospect__in=related,
        campaign=campaign,
    ).count() + 1

    campaign_prospect, _ = prospect.push_to_campaign(
        campaign=campaign,
        is_new_prospect=not prospect.upload_duplicate,
        has_litigator_list=has_litigator_list,
        sort_order=sort_order,
        sms=sms,
    )
    campaign_prospect.from_upload_skip_trace = upload_skip_trace

    address_obj = prospect.prop.address
    if address_obj:
        attom_tags = get_or_create_attom_tags(address_obj, campaign.company)
        tags.extend(attom_tags)

    if tags and prospect.prop:
        prospect.prop.tags.add(*tags)
    prospect.apply_auto_tags(campaign_prospect=campaign_prospect)

    # If not sms, skip the following sms campaign related tasks
    if not sms or campaign.is_direct_mail:
        return charge

    if campaign_prospect.include_in_upload_count and not prospect.upload_duplicate:
        charge = 1

    campaign.update_campaign_stats()

    return charge


def get_dm_charges(company, drop_date=None):
    """"
    Returns post card price per piece for Direct Mail Campaigns.
    """
    today = drop_date
    if not drop_date:
        today = django_tz.now().date()
    discount_start = datetime.strptime(DISCOUNT_START_DATE, '%m-%d-%Y').date()
    discount_end = datetime.strptime(DISCOUNT_END_DATE, '%m-%d-%Y').date()
    if discount_start <= today < discount_end:
        price_per_piece = POST_CARD_DISCOUNT_PRICE
    else:
        price_per_piece = company.postcard_price
    return price_per_piece


def get_target_hours(update_status=False):
    """
    Get target hours to filter DirectMailCampaigns
    The date to send campaign is based on SiteSettings and day of the week.
    The date to update the status is 24 hours after send date.

    :param update_status: Boolean indicating if we are getting the date to update the status.
    """
    # If we are updating the status, it needs to be 24 hours after the order got sent.
    update_status_hours = 0 if not update_status else 24

    # If updating status on Friday or sending orders on Thursday, we want Monday's orders.
    weekday = datetime.today().weekday()
    monday_orders_hours = 96
    if (update_status and weekday == 4) or (weekday == 3 and not update_status):
        return monday_orders_hours - update_status_hours

    site_settings = SiteSettings.load()
    return site_settings.direct_mail_drop_date_hours - update_status_hours
