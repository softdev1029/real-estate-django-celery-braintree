from django.core.management.base import BaseCommand

from companies.tasks import upload_internal_dnc_task
from litigation.tasks import upload_litigator_list_task
from prospects.tasks import upload_prospects_task2
from sherpa.models import SherpaTask, UploadInternalDNC, UploadLitigatorList, UploadProspects
from skiptrace.models import UploadSkipTrace
from skiptrace.tasks import skip_trace_push_to_campaign_task, start_skip_trace_task


class Command(BaseCommand):
    def handle(self, *args, **kwargs):

        upload_prospects_list = UploadProspects.objects.filter(status='auto_stop')

        i = 1  # Start the first task after 10 seconds
        for upload_prospect in upload_prospects_list:
            upload_prospect.stop_upload = False
            # upload_prospect.save()
            upload_prospect.save(update_fields=['stop_upload'])
            upload_prospects_task2.apply_async((upload_prospect.id,), countdown=10 * i)
            i += 1
        print(('Resumed %d Prospect Uploads' % len(upload_prospects_list)))

        upload_litigator_list = UploadLitigatorList.objects.filter(status='auto_stop')
        # Don't reset `i` here. That way we keep queuing tasks every 10 seconds without duplicates.
        for litigator_list in upload_litigator_list:
            litigator_list.stop_upload = False
            # litigator_list.save()
            litigator_list.save(update_fields=['stop_upload'])
            upload_litigator_list_task.apply_async((litigator_list.id,), countdown=10 * i)
            i += 1
        print(('Resumed %d Litigator Uploads' % len(upload_litigator_list)))

        skip_trace_list = UploadSkipTrace.objects.filter(status='auto_stop')
        # Don't reset `i` here. That way we keep queuing tasks every 10 seconds without duplicates.
        for skip_trace in skip_trace_list:
            skip_trace.stop_upload = False
            # skip_trace.save()
            skip_trace.save(update_fields=['stop_upload'])
            start_skip_trace_task.apply_async((skip_trace.id,), countdown=10 * i)
            i += 1
        print(('Resumed %d SkipTrace Uploads' % len(skip_trace_list)))

        skip_trace_push_to_campaign_list = UploadSkipTrace.objects.filter(
            push_to_campaign_status=UploadSkipTrace.PushToCampaignStatus.AUTO_STOP,
        )
        # Don't reset `i` here. That way we keep queuing tasks every 10 seconds without duplicates.
        for skip_trace_push_to_campaign in skip_trace_push_to_campaign_list:
            skip_trace_push_to_campaign.stop_push_to_campaign = False
            skip_trace_push_to_campaign.save(update_fields=['stop_push_to_campaign'])
            skip_trace_push_to_campaign_task.apply_async(
                (skip_trace_push_to_campaign.id,), countdown=10 * i,
            )
            i += 1
        print(('Resumed %d Skip Trace Push To Campaigns' % len(skip_trace_push_to_campaign_list)))

        internal_dnc_list = UploadInternalDNC.objects.filter(status='auto_stop')
        # Don't reset `i` here. That way we keep queuing tasks every 10 seconds without duplicates.
        for internal_dnc in internal_dnc_list:
            internal_dnc.stop_upload = False
            internal_dnc.save(update_fields=['stop_upload'])
            upload_internal_dnc_task.apply_async((internal_dnc.id,), countdown=10 * i)
            i += 1
        print(('Resumed %d Upload Internal DNC' % len(internal_dnc_list)))

        paused_tasks = SherpaTask.objects.filter(status=SherpaTask.Status.PAUSED)
        for task in paused_tasks:
            task.restart_task()
        print(f'Resumed {paused_tasks.count()} tasks.')
