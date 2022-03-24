from urllib.request import urlretrieve

from celery import shared_task

from django.core.files import File

from .models import Call


@shared_task
def save_recording_to_s3(call_id, telnyx_s3_url):
    """
    Saves the mp3 call recording from Telnyx into our s3 bucket.

    :param call_id int: The Call model instance ID that holds data about this call.
    :param telnyx_s3_url string: The url path of the call recording in the Telnyx s3 bucket.
    """

    call = Call.objects.get(id=call_id)
    dt = call.start_time.strftime("%Y%m%d_%H%M%S")
    filename = f"{call.id}_{dt}.mp3"
    result = urlretrieve(telnyx_s3_url)
    call.recording.save(filename, File(open(result[0], "rb")))
    call.save()
