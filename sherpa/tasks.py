from datetime import datetime, timedelta

from boto3.session import Session
from celery import shared_task, task
from dateutil.parser import parse, ParserError

from django.conf import settings
from django.contrib.sites.models import Site
from django.core import mail, management
from django.template.loader import render_to_string

from .models import SherpaTask
from .utils import should_convert_datetime


@shared_task
def sherpa_send_email(subject, template, to_email, context, from_email=settings.DEFAULT_FROM_EMAIL):
    """
    Send emails in an asynchronous task.

    :param subject: The subject of the email
    :param template: Django template to render the email
    :param to_email: User's email that the email should be emailed to
    :param context: Dictionary of data that should be sent to the email template
    """
    for key in context:
        value = context[key]
        if not should_convert_datetime(key):
            continue

        try:
            datetime_obj = parse(value)
            context[key] = datetime_obj
        except (TypeError, ParserError):
            continue

    if 'site_id' in context:
        try:
            context['site'] = Site.objects.get(id=context['site_id'])
        except Site.DoesNotExist:
            pass

    html_message = render_to_string(template, context)
    return mail.send_mail(
        subject,
        'HTML support is required to view this email.',
        from_email,
        [to_email],
        html_message=html_message,
    )


@shared_task
def s3_cleanup_routine():
    """
    Cleans up the bucket the application is responsible for (settings.AWS_STORAGE_BUCKET_NAME).
    Removes non recording files that are older than seven days and removes recording files older
    than six months.
    """
    session = Session(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )

    s3 = session.resource('s3')
    bucket = s3.Bucket(settings.AWS_STORAGE_BUCKET_NAME)

    # Files older than these dates will be removed.
    recording_expire_date = datetime.now() - timedelta(days=6 * 30)  # Assume 30 days per month.
    file_expire_date = datetime.now() - timedelta(days=7)

    expire_lookups = {
        '/uploads/': file_expire_date,
        '/downloads/': file_expire_date,
        '/recordings/': recording_expire_date,
        '/ligitation_uploads/': file_expire_date,
    }

    for f in bucket.objects.all():
        # Lookup the files minimum expiration date.
        expire_date = None
        for lookup, value in expire_lookups.items():
            if lookup in f.key:
                expire_date = value
                break

        if expire_date and (f.last_modified).replace(tzinfo=None) < expire_date:
            f.delete()


@task
def run_open_tasks():
    tasks = SherpaTask.objects.filter(status=SherpaTask.Status.OPEN)
    for t in tasks:
        t.queue_task()


@task
def clear_idle_queries(minutes_idle=10):
    management.call_command("clear_idle_queries", min=minutes_idle)
