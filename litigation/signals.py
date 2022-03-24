from django.db.models.signals import post_save

from litigation.tasks import upload_litigator_list_task
from sherpa.models import UploadLitigatorList


def litigator_uploaded(instance, created, raw, **kwargs):
    if raw or not created:
        return

    upload_litigator_list_task.apply_async([instance.id], countdown=2)


post_save.connect(litigator_uploaded, sender=UploadLitigatorList)
