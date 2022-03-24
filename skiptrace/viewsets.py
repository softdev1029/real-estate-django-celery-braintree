from drf_yasg.utils import swagger_auto_schema

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from companies.models import DownloadHistory
from companies.tasks import generate_download
from core.mixins import CompanyAccessMixin, CSVBulkExporterMixin
from sherpa.csv_uploader import CSVFieldMapper
from sherpa.models import Campaign
from sherpa.utils import get_upload_additional_cost
from .models import SkipTraceProperty, UploadSkipTrace
from .serializers import (
    PushToCampaignGetSerializer,
    PushToCampaignSerializer,
    UploadSkipTraceMapFieldsRequestSerializer,
    UploadSkipTraceResponseSerializer,
    UploadSkipTraceSerializer,
    UploadSkipTraceSingleRequestSerializer,
)
from .tasks import skip_trace_push_to_campaign_task, start_skip_trace_task


class UploadSkipTraceViewSet(CompanyAccessMixin, ListModelMixin, RetrieveModelMixin,
                             GenericViewSet, CSVBulkExporterMixin):
    model = UploadSkipTrace
    serializer_class = UploadSkipTraceSerializer
    filterset_fields = ('status', 'is_archived', 'push_to_campaign_status', 'created_by__id')
    bulk_export_type = DownloadHistory.DownloadTypes.SKIPTRACE

    def get_queryset(self):
        """
        Don't return the skip traces in setup.
        """
        return super().get_queryset().exclude(status=UploadSkipTrace.Status.SETUP)

    def get_skip_trace_in_setup(self, pk):
        """
        Return `UploadSkipTrace` that is in SETUP status for pk given.
        """
        return super().get_queryset().filter(status=UploadSkipTrace.Status.SETUP, pk=pk).first()

    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        """
        Export data from associated `SkipTraceProperty` objects as csv data.
        """
        company = request.user.profile.company
        filename_date = timezone.now().date()
        filters = {
            'filename': f'SKIP-TRACE-{ str(company) }-{ filename_date }.csv',
            'upload_skip_trace_id': self.get_object().id,
        }
        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=company,
            download_type=DownloadHistory.DownloadTypes.SKIPTRACE,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)

        return Response({'id': download.uuid})

    @swagger_auto_schema(
        responses={201: UploadSkipTraceResponseSerializer},
        request_body=UploadSkipTraceMapFieldsRequestSerializer,
    )
    @action(detail=False, methods=['post'],
            serializer_class=UploadSkipTraceMapFieldsRequestSerializer)
    def map_fields(self, request):
        """
        skip-traces_map_fields

        Map fields from FlatFile data response.

        request must have the following:
        `headers_matched`: list of headers matched in Flatfile
        `valid_data`: valid data returned from Flatfile
        `uploaded_filename`: original name of file uploaded
        """
        company = request.user.profile.company

        headers_matched = request.data.get('headers_matched', [])
        data = request.data.get('valid_data', [])
        filename = request.data.get('uploaded_filename')

        # Check that we have the data needed before mapping.
        if not (headers_matched and data and filename):
            data = {
                'detail': 'Must send `headers_matched`, `valid_data` and `uploaded_filename`'
                          ' in request.',
            }
            return Response(data, status=400)

        # TODO: move this up and replace the custom logic above as we normalize on frontend
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # validate that the tags exist and belong to the company
        property_tag_ids = serializer.validated_data.get('property_tag_ids', [])
        company_tag_ids = company.propertytag_set.filter(
            pk__in=property_tag_ids).values_list('pk', flat=True)
        missing_company_tag_ids = set(property_tag_ids) - set(company_tag_ids)
        if missing_company_tag_ids:
            data = {
                "detail": f"Tags {missing_company_tag_ids} do not exist in the Company.",
            }
            return Response(data, status=400)

        csv_mapper = CSVFieldMapper(request)
        csv_mapper.map_upload_skip_trace()

        if property_tag_ids:
            csv_mapper.upload_object.property_tags.add(*property_tag_ids)

        company.refresh_from_db()

        if csv_mapper.success:
            serializer = UploadSkipTraceResponseSerializer(csv_mapper.upload_object)
            return Response(serializer.data, 201)

        return Response({'detail': 'Failed to map columns.'}, status=400)

    @swagger_auto_schema(
        responses={201: UploadSkipTraceResponseSerializer},
        request_body=UploadSkipTraceSingleRequestSerializer,
    )
    @action(detail=False, methods=['post'])
    def single(self, request):
        """
        skip-traces_single

        Create Single record Skip Trace.

        request must include Boolean `propertyOnly` and have at least the following:
        `propertyAddress`, `propertyCity`, `propertyState`, `propertyZip`
        If `propertyOnly` is false, request must also include:
        `firstName`, `lastName`, `mailingAddress`, `mailingCity`, `mailingState`,
        `mailingZip`
        """
        if not request.user.profile.company.has_sherpa_balance():
            data = {
                'detail': "You don't have enough Sherpa Credits to run a Single Skip Trace.",
            }
            return Response(data, status=402)

        skip_trace_property, error = SkipTraceProperty().save_from_single_upload_form(
            request.data, request.user)
        if skip_trace_property:
            serializer = UploadSkipTraceResponseSerializer(skip_trace_property.upload_skip_trace)
            return Response(serializer.data, status=201)

        return Response({'detail': error}, status=400)

    @action(detail=True, methods=['patch'])
    def purchase(self, request, pk=None):
        """
        skip-trace_purchase

        Purchase skip trace and start task.

        `suppress_against_database` defaults to True, to turn it off must pass False in request.
        """
        if not request.user.profile.can_skiptrace:
            return Response({'detail': 'User is not valid to skip trace.'}, status=400)

        # Skip Trace is in 'setup' status, so get it using 'get_skip_trace_in_setup'.
        instance = self.get_skip_trace_in_setup(pk)
        if not instance:
            data = {'detail': 'Bad request. Object does not exist.'}
            return Response(data, status=400)

        instance.suppress_against_database = request.data.get('suppress_against_database', True)
        # Update 'suppress_against_database' whether or not transaction authorizes successfully.
        instance.save(update_fields=['suppress_against_database'])

        if not instance.authorized_successful():
            data = {'detail': instance.transaction.failure_reason}
            return Response(data, status=500)

        if instance.is_prop_stack_upload:
            instance.begin_prop_stack_processing = True
            instance.save(update_fields=['begin_prop_stack_processing'])
            if not instance.prop_stack_file_ready:
                serializer = self.serializer_class(instance)
                return Response(serializer.data)

        instance.status = UploadSkipTrace.Status.SENT_TO_TASK
        instance.save(update_fields=['status'])
        start_skip_trace_task.delay(instance.id)
        serializer = self.serializer_class(instance)

        return Response(serializer.data)

    @swagger_auto_schema(
        method='patch',
        responses={200: 'Updated skip-trace file upload status.'},
    )
    @action(detail=True, methods=['patch'])
    def update_skip_trace_file_upload_status(self, request, pk=None):
        """
        Update skip-trace file upload status like cancel or pause/resume upload.

        Input Parameters:
            status (str): cancel, pause and resume.
        Returns:
            Json Response : Successfully status updated or not.
        """
        try:
            upload_skip_trace_obj = UploadSkipTrace.objects.get(pk=int(pk))
        except UploadSkipTrace.DoesNotExist as err:
            return Response({'detail': str(err)}, status=404)
        status = request.data.get('status', None)
        if status is None:
            return Response({'detail': 'status is missing in request data'}, status=400)
        if status.lower() not in ['cancel', 'pause', 'resume']:
            return Response({'detail': 'Invalid status'}, status=400)
        if status.lower() == 'cancel':
            upload_skip_trace_obj.status = UploadSkipTrace.Status.CANCELLED
            upload_skip_trace_obj.upload_error = "Cancelled by user"
            upload_skip_trace_obj.save(update_fields=['status', 'upload_error'])
        elif status.lower() == 'pause':
            upload_skip_trace_obj.stop_upload = True
            upload_skip_trace_obj.save(update_fields=['stop_upload'])
        elif status.lower() == 'resume':
            upload_skip_trace_obj.stop_upload = False
            upload_skip_trace_obj.save(update_fields=['stop_upload'])
            upload_skip_trace_obj.restart()
        return Response({'detail': 'Updated skip-trace file upload status'}, status=200)

    @swagger_auto_schema(
        method='post',
        responses={200: 'The push to campaign has successfully started.'},
    )
    @swagger_auto_schema(method='get', responses={200: PushToCampaignGetSerializer})
    @action(detail=True, methods=['post', 'get'], serializer_class=PushToCampaignSerializer)
    def push_to_campaign(self, request, pk=None):
        """
        Push the prospects from a skip trace instance into a campaign.
        """
        instance = self.get_object()

        if request.method == 'GET':
            serializer = PushToCampaignGetSerializer(instance=instance)
            return Response(serializer.data)

        # Create transaction and see if we can authorize it if user is over upload limit.
        import_type = request.data.get('import_type')
        cost, exceeds_count = get_upload_additional_cost(
            instance.company,
            instance.rows_to_push_to_campaign(import_type),
            upload=instance,
        )
        # If we can't authorize the transaction, send back an error.
        if cost and not instance.authorize_transaction(cost, push_to_campaign=True):
            data = {'detail': instance.push_to_campaign_transaction.failure_reason}
            return Response(data, status=500)

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get the campaign that we're pushing to.
        campaign_id = request.data.get('campaign')
        campaign = Campaign.objects.filter(id=campaign_id).first()
        if not campaign:
            raise ValidationError(
                {"campaign": [f"Could not find campaign with id {campaign_id}"]})

        # Update the upload skip trace instance.
        instance.push_to_campaign_campaign_id = campaign_id
        instance.push_to_campaign_import_type = import_type
        instance.push_to_campaign_status = UploadSkipTrace.PushToCampaignStatus.QUEUED
        instance.save(update_fields=[
            'push_to_campaign_campaign_id',
            'push_to_campaign_import_type',
            'push_to_campaign_status',
        ])

        skip_trace_push_to_campaign_task.delay(instance.id, request.data.get('tags', []))
        return Response({})
