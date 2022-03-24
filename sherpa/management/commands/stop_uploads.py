from django.core.management.base import BaseCommand

from sherpa.models import SherpaTask, UploadInternalDNC, UploadLitigatorList, UploadProspects
from skiptrace.models import UploadSkipTrace


class Command(BaseCommand):
    def handle(self, *args, **kwargs):

        upload_prospects_list = UploadProspects.objects.filter(status='running')

        for upload_prospect in upload_prospects_list:
            upload_prospect.status = 'auto_stop'
            upload_prospect.stop_upload = True
            # upload_prospect.save()
            upload_prospect.save(update_fields=['status', 'stop_upload'])
        print(('Stopped %d Prospect uploads' % len(upload_prospects_list)))

        upload_litigator_list = UploadLitigatorList.objects.filter(status='running')

        for litigator_list in upload_litigator_list:
            litigator_list.status = 'auto_stop'
            litigator_list.stop_upload = True
            # litigator_list.save()
            litigator_list.save(update_fields=['status', 'stop_upload'])
        print(('Stopped %d Litigator uploads' % len(upload_litigator_list)))

        skip_trace_list = UploadSkipTrace.objects.filter(status=UploadSkipTrace.Status.RUNNING)
        for skip_trace in skip_trace_list:
            skip_trace.status = UploadSkipTrace.Status.AUTO_STOP
            skip_trace.stop_upload = True
            skip_trace.save(update_fields=['status', 'stop_upload'])
        print(('Stopped %d Skip Trace Uploads' % len(skip_trace_list)))

        skip_trace_push_to_campaign_list = UploadSkipTrace.objects.filter(
            push_to_campaign_status='running',
        )
        for skip_trace_push_to_campaign in skip_trace_push_to_campaign_list:
            skip_trace_push_to_campaign.push_to_campaign_status = 'auto_stop'
            skip_trace_push_to_campaign.stop_push_to_campaign = True
            skip_trace_push_to_campaign.save(
                update_fields=['push_to_campaign_status', 'stop_push_to_campaign'],
            )
        print(('Stopped %d Skip Trace Push To Campaigns' % len(skip_trace_push_to_campaign_list)))

        internal_dnc_list = UploadInternalDNC.objects.filter(status='running')
        for internal_dnc in internal_dnc_list:
            internal_dnc.status = 'auto_stop'
            internal_dnc.stop_upload = True
            internal_dnc.save(update_fields=['status', 'stop_upload'])
        print(('Stopped %d Upload Internal DNC' % len(internal_dnc_list)))

        active_tasks = SherpaTask.objects.filter(
            status__in=[SherpaTask.Status.RUNNING, SherpaTask.Status.QUEUED],
        )
        for task in active_tasks:
            task.pause_task()
        print(f'Stopped {active_tasks.count()} tasks.')
