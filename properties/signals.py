from django.db.models.signals import m2m_changed, post_save

from search.tasks import stacker_update_property_tags
from .models import AttomRecorder, PropertyTag, PropertyTagAssignment


def attomrecorder_post_save(sender, instance, **kwargs):
    """
    Adds or removes the Quitclaim tag to all properties connected to this Attom record.
    """
    addresses = instance.attom_id.address_set.all()
    is_qc = instance.quitclaim_flag == 1
    for address in addresses:
        properties = address.properties.all()
        for prop in properties:
            tag = PropertyTag.objects.get(name="Quitclaim", company_id=prop.company_id)
            if is_qc:
                prop.tags.add(tag)
            else:
                prop.tags.remove(tag)


def property_tag_post_save(sender, instance, created, raw, **kwargs):
    if not created or raw:
        return

    # Save the property tag with the highest order,so that it's last by default.
    last_tag = instance.company.propertytag_set.last()
    instance.order = last_tag.order + 1 if last_tag else 1
    instance.save(update_fields=["order"])


def tags_updated_on_property(instance, action, **kwargs):
    if action not in ["post_add", "post_remove"]:
        return

    pta = PropertyTagAssignment.objects.filter(
        prop_id=instance.id,
    ).values(
        'tag_id',
        'tag__distress_indicator',
    )

    tags = [tag['tag_id'] for tag in pta]
    distress = len([tag['tag_id'] for tag in pta if tag['tag__distress_indicator']])

    stacker_update_property_tags.delay(
        instance.id,
        tags,
        distress,
    )


post_save.connect(attomrecorder_post_save, sender=AttomRecorder)
post_save.connect(property_tag_post_save, sender=PropertyTag)
m2m_changed.connect(tags_updated_on_property, sender=PropertyTagAssignment)
