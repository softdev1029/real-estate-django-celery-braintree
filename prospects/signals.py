import uuid

from django.db.models.signals import post_save, pre_save

from prospects.models import ProspectTag
from sherpa.models import Prospect


def prospect_pre_save(sender, instance, raw, **kwargs):
    # When we create a new prospect, we need to check whether it's phone number is opted out
    if raw:
        return

    if instance._state.adding:  # The instance is being created on the db, not updated
        if Prospect.objects.filter(phone_raw=instance.phone_raw, opted_out=True).exists():
            instance.opted_out = True


def prospect_post_save(sender, instance, created, raw, **kwargs):
    """
    When a prospect is created, we need to assign the related record id to group it with similarly
    loaded prospects.
    """
    if not created or raw:
        return

    # Only do this check for related record id on creation.
    if instance.cloned_from and instance.cloned_from.related_record_id:
        instance.related_record_id = instance.cloned_from.related_record_id
    elif not instance.related_record_id:
        # All prospects should have a related record id.
        instance.related_record_id = uuid.uuid4()

    # TODO: This should be removed after we have the `token` field removed.
    if not instance.uuid_token:
        instance.uuid_token = instance.token

    instance.save()


def prospect_tag_post_save(sender, instance, created, raw, **kwargs):
    if not created or raw:
        return

    # Save the prospect tag with the highest order,so that it's last by default.
    last_tag = instance.company.prospecttag_set.last()
    instance.order = last_tag.order + 1 if last_tag else 1
    instance.save(update_fields=['order'])


pre_save.connect(prospect_pre_save, sender=Prospect)

post_save.connect(prospect_post_save, sender=Prospect)
post_save.connect(prospect_tag_post_save, sender=ProspectTag)
