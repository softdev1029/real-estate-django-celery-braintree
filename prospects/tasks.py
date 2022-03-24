from celery import shared_task
from smartystreets_python_sdk import Batch
from smartystreets_python_sdk.us_street import Lookup

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.utils import IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone

from services.smarty import smarty_client
from sherpa.models import PhoneType, Prospect, UploadProspects


@shared_task
def send_upload_email_confirmation_task(upload_prospects_id):
    """
    Alerts user that upload is complete
    """
    upload_prospect = UploadProspects.objects.get(id=upload_prospects_id)
    rep = upload_prospect.created_by

    email_address = rep.email

    if email_address and not upload_prospect.email_confirmation_sent:
        subject = 'Upload Complete - Ref# %s' % upload_prospect.id
        from_email = settings.DEFAULT_FROM_EMAIL
        to = email_address
        text_content = 'Upload Complete'
        html_content = render_to_string('email/email_prospect_upload_confirmation.html',
                                        {'upload_prospect': upload_prospect, 'rep': rep})
        email = EmailMultiAlternatives(subject, text_content, from_email, [to])
        email.attach_alternative(html_content, "text/html")

        email.send()

        upload_prospect.email_confirmation_sent = True
        upload_prospect.save(update_fields=['email_confirmation_sent'])


@shared_task  # noqa: C901
def upload_prospects_task2(upload_prospects_id, tags=None):
    """
    Upload prospects directly into a campaign.
    """
    from .utils import ProcessProspectUpload
    ProcessProspectUpload(UploadProspects.objects.get(id=upload_prospects_id), tags).start()


@shared_task
def update_prospect_after_create(
        prospect_id,
        upload_id,
        sort_order,
        is_new_prospect,
        has_litigator_list,
):
    """
    Update prospect after create.
    """
    prospect = Prospect.objects.get(id=prospect_id)
    prospect.update_phone_type_and_carrier()

    # Run tasks associated with `UploadProspect`, including push to campaign.
    # Must run after phone type lookup.
    upload = UploadProspects.objects.get(id=upload_id) if upload_id else None
    campaign_prospect, sort_order = prospect.upload_prospect_tasks(
        upload,
        sort_order,
        is_new_prospect,
        has_litigator_list,
    )

    # Apply auto tags to `Prospect`.
    try:
        prospect.apply_auto_tags(campaign_prospect=campaign_prospect)
    except IntegrityError:
        pass


@shared_task
def update_prospect_async(prospect_id):
    """
    Update prospect after create for tasks that are always asynchronous.
    """
    from prospects.utils import attempt_auto_verify

    prospect = Prospect.objects.get(id=prospect_id)
    if prospect.company.auto_verify_prospects:
        attempt_auto_verify(prospect)

    # call validate address here
    if not prospect.validated_property_status and \
            prospect.raw_address_to_validate_type != "no_address":
        validate_address_single_task.delay(prospect.id)


@shared_task
def validate_address_single_task(prospect_id):
    """
    Use SmartyStreets to validate single address
    """
    prospect = Prospect.objects.get(id=prospect_id)

    # still use batch process with SS since I have that code
    batch = Batch()
    lookup_count = 0

    # Priority = Full Address, Street + Zip, Street + City + State
    if prospect.raw_address_to_validate_type == 'full_address':
        batch.add(Lookup())
        batch[lookup_count].street = "%s, %s %s %s" % (
            prospect.property_address, prospect.property_city, prospect.property_state,
            prospect.property_zip)
    elif prospect.raw_address_to_validate_type == 'address_zip':
        batch.add(Lookup())
        batch[lookup_count].street = prospect.property_address
        batch[lookup_count].zipcode = prospect.property_zip
    elif prospect.raw_address_to_validate_type == 'address_city_state':
        batch.add(Lookup())
        batch[lookup_count].street = prospect.property_address
        batch[lookup_count].city = prospect.property_city
        batch[lookup_count].state = prospect.property_state
    else:
        # set property status to invalid
        # Add a invalid address for lookup to keep counter accurate (just in case)
        batch.add(Lookup())
        batch[lookup_count].street = "123 Invalid address"

    smarty_client.send_batch(batch)

    for i, lookup in enumerate(batch):
        candidates = lookup.result
        if len(candidates) == 0:
            prospect.validated_property_status = 'invalid'
        else:
            candidate = candidates[0]
            components = candidate.components
            metadata = candidate.metadata
            analysis = candidate.analysis

            address = f"{candidate.delivery_line_1} {candidate.delivery_line_2}" \
                if candidate.delivery_line_2 else candidate.delivery_line_1
            prospect.validated_property_status = 'validated'
            prospect.property_address = address
            prospect.property_city = components.city_name
            prospect.property_state = components.state_abbreviation
            prospect.property_zip = components.zipcode
            prospect.validated_property_vacant = analysis.vacant
            prospect.validated_property_delivery_line_1 = candidate.delivery_line_1
            prospect.validated_property_delivery_line_2 = candidate.delivery_line_2
            prospect.validated_property_plus4_code = components.plus4_code
            prospect.validated_property_latitude = metadata.latitude
            prospect.validated_property_longitude = metadata.longitude

        prospect.save(update_fields=[
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'validated_property_status',
            'validated_property_vacant',
            'validated_property_delivery_line_1',
            'validated_property_delivery_line_2',
            'validated_property_plus4_code',
            'validated_property_latitude',
            'validated_property_longitude',
        ])


@shared_task
def update_phone_data(phone_id):
    """
    Updates the PhoneType instance and any prospect that uses the number.

    :param phone_id int: The ID of the PhoneType instance.
    """
    try:
        instance = PhoneType.objects.get(id=phone_id)
    except PhoneType.DoesNotExist:
        return

    if instance.last_carrier_lookup == timezone.now().date():
        # Ignore updating if we've already looked up this phone today.
        return

    instance.lookup_phone_type()
    instance.refresh_from_db()

    # Update all phone types of the same phone across all companies with the new data.
    PhoneType.objects.exclude(pk=instance.pk).filter(phone=instance.phone).update(
        carrier=instance.carrier,
        type=instance.type,
        last_carrier_lookup=instance.last_carrier_lookup,
    )

    # Update all prospects of the same phone across all companies with the new data.
    Prospect.objects.filter(phone_raw=instance.phone).update(
        phone_type=instance.type,
        phone_carrier=instance.carrier,
    )
