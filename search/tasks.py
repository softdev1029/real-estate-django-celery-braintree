import csv
from io import StringIO
from typing import List

from celery import shared_task

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q

from billing.models import Transaction
from sherpa.models import CampaignProspect, Prospect, SherpaTask
from sherpa.utils import get_upload_additional_cost
from skiptrace.models import UploadSkipTrace
from .indexes.stacker import StackerIndex
from .utils import (
    build_elasticsearch_painless_scripts,
    build_update_for_query_body,
    get_or_create_campaign,
)

User = get_user_model()


@shared_task
def stacker_update_address_data(address_id, changes):
    """
    Updates the documents that contain the address_id with the changes.
    """
    if not changes:
        return
    body = build_update_for_query_body(
        "address",
        address_id,
        build_elasticsearch_painless_scripts(changes),
    )
    StackerIndex.update_by_query(StackerIndex.prospect_index_name, body)
    StackerIndex.update_by_query(StackerIndex.property_index_name, body)


@shared_task
def stacker_update_property_data(property_id, changes):
    """
    Updates the documents that contain the property_id with the changes.
    """
    if not changes:
        return
    body = build_update_for_query_body(
        "property",
        property_id,
        build_elasticsearch_painless_scripts(changes),
    )
    StackerIndex.update_by_query(StackerIndex.prospect_index_name, body)
    StackerIndex.update_by_query(StackerIndex.property_index_name, body)


@shared_task
def stacker_update_prospect_data(prospect_id, changes):
    """
    Updates the documents that contain the prospect_id with the changes.
    """
    if not changes:
        return
    body = build_update_for_query_body(
        "prospect",
        prospect_id,
        build_elasticsearch_painless_scripts(changes),
    )
    StackerIndex.update_by_query(StackerIndex.prospect_index_name, body)
    StackerIndex.update_by_query(StackerIndex.property_index_name, body)


@shared_task
def stacker_full_update(prospect_id, property_id):
    """
    Adds property data to the prospect document and prospect data to the property document.

    :param prospect_id list: List of prospect IDs.
    :param property_id list: List of property IDs.
    """
    StackerIndex.full_update(tuple(property_id), tuple(prospect_id))


@shared_task
def stacker_update_property_tags(property_id, tags, distress_indicators):
    """
    Updates the documents that contain the property_id with the tag changes.

    :param property_id int: The ID of the property whose tag has been updated.
    :param tags list: A list of tag IDs that belong to the property.
    :param distress_indicators int: The number of tags in param tags who are distress indicators.
    """

    script = f"""
        ctx._source.tags={tags};
        ctx._source.tags_length={len(tags)};
        ctx._source.distress_indicators={distress_indicators};
    """

    body = build_update_for_query_body(
        "property",
        property_id,
        script,
    )
    StackerIndex.update_by_query(StackerIndex.prospect_index_name, body)
    StackerIndex.update_by_query(StackerIndex.property_index_name, body)


@shared_task
def prepare_tags_for_index_update(property_id):
    """
    Grabs the tags in each property in the list of property ids and sends them to update the index.

    :param property_id list: List of property IDs to update.
    """
    from properties.models import PropertyTagAssignment
    for id in property_id:
        pta = PropertyTagAssignment.objects.filter(
            prop_id=id,
        ).values(
            'tag_id',
            'tag__distress_indicator',
        )
        tags = [tag['tag_id'] for tag in pta]
        distress = len([tag['tag_id'] for tag in pta if tag['tag__distress_indicator']])
        stacker_update_property_tags.delay(id, tags, distress)


@shared_task
def handle_prospect_tag_update(
        user_id: int,
        prospect_id: List[int],
        toggles: dict,
        is_adding: bool,
):
    user = User.objects.get(id=user_id)
    tags = toggles.pop("tags", [])
    if tags:
        properties_ids = list(Prospect.objects.filter(
            id__in=prospect_id,
            prop__isnull=False,
        ).values_list("prop__id", flat=True))
        if properties_ids:
            handle_property_tagging(properties_ids, tags, is_adding)

    with transaction.atomic():
        for p in Prospect.objects.select_for_update().filter(id__in=prospect_id):
            if "wrong_number" in toggles:
                p.toggle_wrong_number(user, toggles["wrong_number"], index_update=False)
            if "do_not_call" in toggles:
                p.toggle_do_not_call(user, toggles["do_not_call"], index_update=False)
            if "is_priority" in toggles:
                p.toggle_is_priority(user, toggles["is_priority"], index_update=False)
            if "is_qualified_lead" in toggles:
                p.toggle_qualified_lead(user, toggles["is_qualified_lead"], index_update=False)
        if "opted_out" in toggles:
            Prospect.objects.filter(id__in=prospect_id).update(opted_out=toggles["opted_out"])
    if toggles:
        stacker_update_prospect_data.delay(prospect_id, toggles)


@shared_task
def push_to_campaign_task(task_id):
    """
    A task
    """
    from campaigns.utils import push_to_campaign

    task = SherpaTask.objects.get(id=task_id)
    if task.pause:
        return
    task.start_task()
    task.refresh_from_db()
    attributes = task.attributes
    is_direct_mail = attributes.get("direct_mail", False)
    try:
        campaign = get_or_create_campaign(task)
        if not campaign:
            return
        remaining_prospects = Prospect.objects.filter(
            id__in=attributes.get("id_list"),
            company_id=task.company_id,
        ).exclude(pk__in=campaign.prospects.values_list("id", flat=True))
        for prospect in remaining_prospects:
            task.refresh_from_db()
            if task.pause:
                return
            charge = push_to_campaign(
                campaign,
                prospect,
                tags=attributes.get("tags"),
                upload_skip_trace=None,
                sms=not is_direct_mail,
            )
            if not is_direct_mail:
                attributes["charge"] += charge
                task.attributes = attributes
                task.save(update_fields=["attributes"])

        campaign_prospects = CampaignProspect.objects.filter(
            campaign=campaign,
            prospect__pk__in=attributes.get("id_list"),
        )
        if not is_direct_mail and attributes.get("transaction_id", None):
            trans = Transaction.objects.get(id=attributes.get("transaction_id"))
            cost, _ = get_upload_additional_cost(task.company, attributes.get("charge"))
            trans.charge(cost)
        metrics = {"total_prospects": campaign_prospects.count()}
        if is_direct_mail:
            campaign.update_campaign_stats()
            metrics.update({
                "mobile": campaign_prospects.filter(prospect__phone_type="mobile").count(),
                "landline": campaign_prospects.filter(prospect__phone_type="landline").count(),
                "skipped": campaign_prospects.filter(skipped=True).count(),
                "litigator": campaign_prospects.filter(
                    Q(is_associated_litigator=True) | Q(is_litigator=True)).count(),
            })

            # Verify if order should be auth and locked.
            dmc = campaign.directmail
            dmc.attempt_auth_and_lock()
        task.refresh_from_db()
        task.complete_task(metrics=metrics)
        prop_ids = list(Prospect.objects.filter(
            id__in=attributes.get("id_list"),
        ).values_list("prop_id", flat=True))
        stacker_full_update.delay(attributes.get("id_list"), prop_ids)
    except Exception as e:
        task.set_error(error_msg=str(e))


@shared_task
def populate_by_company_id(company_id):
    """
    Populates both the prospect and property indexes by company id.

    :param company_id list: List of company IDs to load.
    """
    StackerIndex.populate_property_by_company(company_id)
    StackerIndex.populate_prospect_by_company(company_id)


@shared_task
def handle_property_tagging(id_list: List[int], tag_ids: List[int], is_adding: bool):
    """
    Task to tag properties

    :param id_list list: List of property IDs.
    :param tag_ids list: List of tag IDs.
    :param is_adding bool: Determines if we should be adding or removing the tags
    """
    from properties.models import PropertyTagAssignment
    if is_adding:
        assignments = [
            PropertyTagAssignment(
                tag_id=tag_id,
                prop_id=prop_id,
            )
            for tag_id in tag_ids
            for prop_id in id_list
        ]
        PropertyTagAssignment.objects.bulk_create(assignments, ignore_conflicts=True)
    else:
        PropertyTagAssignment.objects.filter(
            Q(prop_id__in=id_list) & Q(tag_id__in=tag_ids),
        ).delete()

    prepare_tags_for_index_update.delay(id_list)


@shared_task
def handle_skip_trace_task(company_id, user_id, id_list, upload_id):
    """
    Handles skip tracing the provided id_list by first creating a CSV and following the normal
    upload skip trace routine.

    :param company_id int: The ID of the company making the Skip trace request.
    :param user_id int: The ID of the user making the Skip trace request.
    :param id_list list: List of property IDs used to grab the needed data for skip tracing.
    :param upload_id int: ID of the upload skip trace model.
    """
    from properties.models import Property
    queryset = Property.objects.select_related("prospect_set").filter(
        company_id=company_id,
        id__in=id_list,
    ).values(
        "prospect__first_name",
        "prospect__last_name",
        "mailing_address__address",
        "mailing_address__city",
        "mailing_address__state",
        "mailing_address__zip_code",
        "address__address",
        "address__city",
        "address__state",
        "address__zip_code",
    ).order_by("id").distinct("id")

    upload_skip = UploadSkipTrace.objects.get(id=upload_id)
    filename = upload_skip.uploaded_filename

    # Create skip trace csv
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "First Name",
        "Last Name",
        "Mail Address",
        "Mail City",
        "Mail Zip",
        "Property Address",
        "Property City",
        "Property State",
        "Property Zip",
    ])
    for row in queryset.iterator():
        writer.writerow(list(row.values()))

    upload_skip.file.save(
        filename,
        ContentFile(output.getvalue().encode("utf-8")),
    )
    upload_skip.path = upload_skip.file.name
    upload_skip.prop_stack_file_ready = True
    upload_skip.save(update_fields=["path", "prop_stack_file_ready"])

    upload_skip.refresh_from_db()
    if upload_skip.begin_prop_stack_processing:
        from skiptrace.tasks import start_skip_trace_task
        upload_skip.status = UploadSkipTrace.Status.SENT_TO_TASK
        upload_skip.save(update_fields=['status'])
        start_skip_trace_task.delay(upload_skip.id)
