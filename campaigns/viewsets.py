from datetime import datetime, timedelta

from django_filters import rest_framework as filters
from drf_yasg.utils import swagger_auto_schema

from django.contrib.auth import get_user_model
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Case, CharField, Count, F, Q, Value, When, Window
from django.db.models.functions import Concat, DenseRank
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import SearchFilter
from rest_framework.mixins import (
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from billing.models import Transaction
from campaigns.models import DirectMailOrder
from companies.models import DownloadHistory, UploadBaseModel
from companies.tasks import generate_download, modify_freshsuccess_account
from core.filters import NullsAlwaysLastOrderingFilter
from core.mixins import CompanyAccessMixin, CreatedByMixin, CSVBulkExporterMixin
from properties.models import PropertyTagAssignment
from prospects.serializers import CampaignProspectSerializer
from prospects.tasks import upload_prospects_task2
from search.serializers import StackerSinglePropertyTagSerializer
from search.tasks import (
    handle_prospect_tag_update,
    prepare_tags_for_index_update,
    stacker_full_update,
)
from sherpa.csv_uploader import CSVFieldMapper
from sherpa.docs import expandable_query_parameters
from sherpa.models import (
    Campaign,
    CampaignProspect,
    LeadStage,
    Prospect,
    SMSTemplate,
    StatsBatch,
    UploadProspects,
)
from sherpa.pagination import SherpaPagination
from sherpa.permissions import AdminPlusModifyPermission, HasPaymentPermission
from sms.models import SMSTemplateCategory
from .directmail import DirectMailProvider
from .directmail_clients import YellowLetterClient
from .docs import (
    batch_prospects_params,
    direct_mail_params,
    export_params,
    start_upload_params,
    yellow_letter_params,
)
from .filters import CampaignFilter
from .models import CampaignNote, CampaignTag, DirectMailCampaign
from .serializers import (
    CampaignBulkArchiveSerializer,
    CampaignFullStatsSerializer,
    CampaignIssueSerializer,
    CampaignListSerializer,
    CampaignMinimumSerializer,
    CampaignNoteSerializer,
    CampaignReturnSerializer,
    CampaignSerializer,
    CampaignTagSerializer,
    DirectMailCampaignAggregateStatsSerializer,
    DirectMailCampaignResponseSerializer,
    DirectMailCampaignSerializer,
    DirectMailCampaignStatsSerializer,
    DirectMailCampaignTrackingSerializer,
    DirectMailCampaignUpdateSerializer,
    DirectMailOrderSerializer,
    DirectMailTemplatesSerializer,
    DMCampaignListProspectsSerializer,
    FollowupCampaignSerializer,
    ModifyCampaignTagsSerializer,
    ProspectTagByCampaignSerializer,
    RemoveDMCampaignRecipientsSerializer,
    RetrieveDirectMailEventDatesSerializer,
    StatsBatchSerializer,
    UploadProspectsRequestSerializer,
    UploadProspectsResponseSerializer,
    UploadProspectsSerializer,
    YellowLetterTargetDateResponseSerializer,
)
from .tasks import transfer_campaign_prospects
from .utils import get_campaigns_by_access

User = get_user_model()


class CampaignViewSet(
        CompanyAccessMixin,
        CreateModelMixin,
        RetrieveModelMixin,
        ListModelMixin,
        UpdateModelMixin,
        CSVBulkExporterMixin,
        GenericViewSet):
    serializer_class = CampaignSerializer
    permission_classes = (IsAuthenticated, AdminPlusModifyPermission)
    model = Campaign
    filter_backends = (filters.DjangoFilterBackend, SearchFilter, NullsAlwaysLastOrderingFilter)
    ordering_fields = ('created_date', 'name', 'percent', 'directmail__order_id__drop_date',
                       'directmail__order_id__status', 'campaign_stats__total_leads')
    expandable_fields = ('market', 'created_by', 'is_direct_mail')
    filterset_class = CampaignFilter
    search_fields = ('name',)
    bulk_export_type = DownloadHistory.DownloadTypes.CAMPAIGN_PROSPECT

    def get_queryset(self):
        """
        Returns a queryset of campaigns the request user has access to and calculates the percent
        complete of each campaign for the purpose of sorting and filtering.
        """
        return get_campaigns_by_access(self.request.user)

    def __get_cp_queryset(self, query_params):
        """
        Return a queryset of campaign prospects that should be used in an export.
        """
        lead_stage_id = query_params.get('lead_stage')
        is_priority_unread = query_params.get('is_priority_unread') == 'true'
        phone_type = query_params.get('phone_type')
        campaign = self.get_object()

        if is_priority_unread or lead_stage_id:
            params = dict()
            # Get the lead stage to filter to.
            if lead_stage_id:
                try:
                    lead_stage = LeadStage.objects.get(
                        id=lead_stage_id,
                        company=self.request.user.profile.company,
                    )
                    params['prospect__lead_stage'] = lead_stage
                except LeadStage.DoesNotExist:
                    # Can't use standard `get_object_or_404` because of the CSVRenderer response.
                    return Response(
                        {'detail': 'Lead stage not found'},
                        status=404,
                        content_type='application/json',
                    )

            # Prepare the data that should be added to the csv.
            cp_queryset = campaign.campaignprospect_set.filter(**params)
        else:
            base_queryset = campaign.campaignprospect_set.all()
            search_phone_types = ['mobile', 'landline']
            if phone_type in search_phone_types:
                cp_queryset = base_queryset.filter(phone_type=phone_type)
            elif phone_type == 'other':
                cp_queryset = base_queryset.exclude(phone_type__in=search_phone_types)
            elif phone_type == 'litigator':
                cp_queryset = base_queryset.filter(
                    Q(is_associated_litigator=True) | Q(is_litigator=True),
                )
            elif phone_type == 'dnc':
                cp_queryset = base_queryset.filter(prospect__do_not_call=True)
            else:
                cp_queryset = base_queryset

        # Filter by priority unread for any type of filter.
        if is_priority_unread:
            cp_queryset = cp_queryset.filter(
                Q(prospect__is_priority=True) | Q(prospect__has_unread_sms=True))

        return cp_queryset

    def get_serializer_class(self):
        """
        Return a slim serializer for the list view.
        """
        if self.action == 'list':
            return CampaignListSerializer
        return self.serializer_class

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(responses={201: CampaignReturnSerializer})
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @swagger_auto_schema(responses={200: CampaignReturnSerializer})
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @swagger_auto_schema(responses={200: CampaignReturnSerializer})
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def perform_update(self, serializer):
        """
        Need to look at the access that's being supplied and update the company access accordingly.
        """
        # Since access is a custom field, we need to remove it before saving the serializer.
        access = serializer.validated_data.pop('access_list', None)
        campaign = serializer.save()
        if access is not None:
            user = self.request.user
            campaign.update_access(set(access), user)

    def perform_create(self, serializer):
        """
        Save the request user's company as the campaign company, the created_by as the user, and
        create the `CampaignAccess` instances.
        """
        self.__create_campaign(serializer)

    def __create_campaign(self, serializer):
        """
        Save the request user's company as the campaign company, the created_by as the user, and
        create the `CampaignAccess` instances.
        """
        # Since access is a custom field, we need to remove it before saving the serializer.
        access = serializer.validated_data.pop('access_list', None)
        user = self.request.user
        campaign = serializer.save(company=user.profile.company, created_by=user)
        if access is not None:
            campaign.update_access(set(access), user)
        return campaign

    @swagger_auto_schema(
        request_body=DirectMailCampaignSerializer,
        responses={201: DirectMailCampaignResponseSerializer},
    )
    @action(detail=False, methods=['post'])
    def direct_mail(self, request):
        """
        Create `DirectMailCampaign`
        """
        from .serializers import SherpaUserSerializer

        # Validate request data before creating campaign.
        data = request.data
        data['campaign']['company'] = request.user.profile.company.id
        user = SherpaUserSerializer(data=request.user)
        user.is_valid()
        data['campaign']['created_by'] = user.data

        # Added since model constrain is not blank or null
        # but from the front end null values are passed.
        temp_budget_per_order = request.data.get('budget_per_order')
        if not temp_budget_per_order:
            request.data['budget_per_order'] = 0

        serializer = DirectMailCampaignSerializer(data=request.data)
        serializer.is_valid()

        if not serializer.is_valid():
            return Response({'details': serializer.errors}, 400)

        from_id = serializer.validated_data['from_id']
        from_user = get_object_or_404(User, pk=from_id)

        campaign_serializer = self.serializer_class(
            data=request.data.pop('campaign'),
            context={'request': request},
        )
        campaign_serializer.is_valid()
        campaign = self.__create_campaign(campaign_serializer)

        drop_date = serializer.validated_data.get('drop_date')
        return_address = serializer.validated_data.get('return_address')
        return_city = serializer.validated_data.get('return_city')
        return_state = serializer.validated_data.get('return_state')
        return_zip = serializer.validated_data.get('return_zip')
        return_phone = serializer.validated_data.get('return_phone')
        template = serializer.validated_data.get('template')
        creative_type = serializer.validated_data.get('creative_type')
        note_for_processor = serializer.validated_data.get('note_for_processor')
        budget_per_order = serializer.validated_data.get('budget_per_order', 0)

        direct_mail_campaign = DirectMailCampaign.objects.create(
            campaign=campaign,
            provider=DirectMailProvider.YELLOWLETTER,
            budget_per_order=budget_per_order,
        )

        direct_mail_campaign.setup_return_address(
            from_user,
            return_address,
            return_city,
            return_state,
            return_zip,
            return_phone,
        )
        direct_mail_campaign.setup_order(drop_date, template, creative_type, note_for_processor)

        serializer = DirectMailCampaignResponseSerializer(direct_mail_campaign)
        # Refresh data to fresh success
        company_id = campaign.company.id
        modify_freshsuccess_account.delay(company_id)
        return Response(serializer.data, 201)

    @swagger_auto_schema(responses={200: DirectMailCampaignUpdateSerializer})
    @action(detail=True, methods=['patch'], url_path='direct_mail')
    def direct_mail_update(self, request, pk=None):
        """
        Update DirectMailCampaign.
        """
        dm_campaign = get_object_or_404(DirectMailCampaign, pk=pk)
        campaign_data = request.data.pop('campaign', None)

        if campaign_data:
            access = campaign_data.pop('access', None)
            campaign_serializer = CampaignSerializer(
                instance=dm_campaign.campaign,
                data=campaign_data,
                partial=True,
                context={'request': request},
            )
            campaign_serializer.is_valid(raise_exception=True)
            campaign = campaign_serializer.save()
            if access is not None:
                user = self.request.user
                campaign.update_access(set(access), user)

        order_data = request.data.pop('order', None)
        from_data = request.data.pop('return_address', None)

        serializer = DirectMailCampaignUpdateSerializer(
            instance=dm_campaign,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        if order_data:
            drop_date = order_data.get('drop_date', None)
            if drop_date:
                date_time_obj = datetime.strptime(drop_date, '%m/%d/%Y')
                order_data['drop_date'] = date_time_obj.date()
            order_serializer = DirectMailOrderSerializer(
                instance=dm_campaign.order,
                data=order_data,
                partial=True,
            )
            order_serializer.is_valid(raise_exception=True)
            order_serializer.save()

            if drop_date:
                dm_campaign.attempt_auth_and_lock()
        if from_data:
            from_user = None
            if from_data.get('from_user'):
                from_user = get_object_or_404(User, pk=from_data.get('from_user'))

            params = {
                'user': from_user,
                'phone': from_data.get('phone'),
                'street': None,
                'city': None,
                'state': None,
                'zipcode': None,
            }
            address_data = from_data.get('address')
            if address_data:
                params['street'] = address_data.get('address')
                params['city'] = address_data.get('city')
                params['state'] = address_data.get('state')
                params['zipcode'] = address_data.get('zip_code')

            dm_campaign.return_address.update(**params)

        return Response(serializer.data)

    @swagger_auto_schema(responses={200: DirectMailCampaignTrackingSerializer})
    @action(detail=True, methods=['get'], url_path='direct_mail_tracking_stats')
    def direct_mail_tracking_stats(self, request, pk=None):
        """
        Get Direct Mail tracking stats.
        """
        dm_campaign = get_object_or_404(DirectMailCampaign, pk=pk)
        stats = dm_campaign.order.tracking_stats
        serializer = DirectMailCampaignTrackingSerializer(instance=stats)
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: DirectMailCampaignAggregateStatsSerializer})
    @action(detail=True, methods=['get'])
    def direct_mail_aggregate_stats(self, request, pk=None):
        """
        Get Direct Mail tracking stats.
        """
        dm_campaign = get_object_or_404(DirectMailCampaign, pk=pk)
        order = dm_campaign.order
        serializer = DirectMailCampaignAggregateStatsSerializer(instance=order)
        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=direct_mail_params,
        responses={200: DirectMailTemplatesSerializer},
    )
    @action(detail=False, methods=['get'])
    def direct_mail_templates(self, request):
        """
        Return valid templates for Direct Mail based on provider.
        """
        provider = request.query_params.get('provider', DirectMailProvider.YELLOWLETTER)
        data = [{'id': x[0], 'name': x[1]} for x in DirectMailProvider.TEMPLATES[provider]]
        serializer = DirectMailTemplatesSerializer(data, many=True)

        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=yellow_letter_params,
        responses={200: YellowLetterTargetDateResponseSerializer},
    )
    @action(detail=False, methods=['get'])
    def direct_mail_target_date(self, request):
        """
        Return next valid target date.
        """
        date = request.query_params.get('date')
        if not date:
            return Response(
                {'detail': 'Must provide a date in the query params'}, status=400)
        client = YellowLetterClient()
        response = client.get_next_target_date(date)
        return Response(response.json())

    @swagger_auto_schema(responses={200: RetrieveDirectMailEventDatesSerializer})
    @action(detail=True, methods=['get'])
    def direct_mail_event_dates(self, request, pk=None):
        campaign = get_object_or_404(Campaign, pk=pk)
        dm_campaign = get_object_or_404(DirectMailCampaign, campaign=campaign)
        serializer = RetrieveDirectMailEventDatesSerializer(dm_campaign.order,
                                                            context={'campaign_pk': pk})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def direct_mail_cancel(self, request, pk=None):
        campaign = get_object_or_404(Campaign, pk=pk)
        dm_campaign = get_object_or_404(DirectMailCampaign, campaign=campaign)
        try:
            dm_campaign.cancel_order()
        except ValueError:
            Response(
                "Direct Mail campaign is past the stage where cancelling is possible",
                status=403,
            )

        return Response(status=200)

    @swagger_auto_schema(responses={200: RetrieveDirectMailEventDatesSerializer})
    @action(detail=True, methods=['get'])
    def auto_calc_of_direct_mail_dates(self, request, pk=None):
        """
        Logic to auto calc the dates associated with DM Campaign
        """
        campaign = get_object_or_404(Campaign, pk=pk)
        dm_campaign = get_object_or_404(DirectMailCampaign, campaign=campaign)
        order_obj = dm_campaign.order
        order_obj.received_by_print_date = order_obj.drop_date - timedelta(days=2)
        order_obj.in_production_date = order_obj.drop_date - timedelta(days=2)
        order_obj.in_transit_date = order_obj.drop_date - timedelta(days=1)
        order_obj.processed_for_delivery_date = order_obj.drop_date
        order_obj.delivered_date = order_obj.drop_date
        order_obj.save(
            update_fields=['received_by_print_date', 'in_production_date',
                           'in_transit_date', 'processed_for_delivery_date',
                           'delivered_date'],
        )
        serializer = RetrieveDirectMailEventDatesSerializer(order_obj,
                                                            context={'campaign_pk': pk})
        return Response(serializer.data)

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, permission_classes=[AllowAny], methods=['post'])
    def direct_mail_tracking(self, request):
        """
        Webhook to receive tracking URL
        """
        notification_key = request.data.get('notification_key')

        # If the notification key is 'job_id' just return.
        # We can get the same data from the `tracking_link` request.
        # No need to make two database saves.
        if notification_key == 'job_id':
            return Response({'success': True})

        reference = request.data.get('ref_id')
        url = request.data.get('notification_value')
        imb = request.data.get('imb')
        barcode = request.data.get('barcode')

        # TODO: Switch this back. This is to handle the few cases that got set
        # wrong early on.
        # order = get_object_or_404(DirectMailOrder, order_id=reference)
        orders = DirectMailOrder.objects.filter(order_id=reference)
        for order in orders.all():
            order.setup_tracking(reference, url, imb, barcode)
        return Response({'success': True})

    @swagger_auto_schema(
        request_body=CampaignBulkArchiveSerializer,
        responses={200: '{"rows_updated": number_of_updated_rows}'},
    )
    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated, AdminPlusModifyPermission],
    )
    def bulk_archive(self, request):
        """
        Custom action to allow for bulk archival of campaigns.
        """
        serializer = CampaignBulkArchiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_list = serializer.validated_data.get('id_list')
        is_archived = serializer.validated_data.get('is_archived')
        rows_updated = Campaign.objects.archive(
            archive=is_archived,
            id__in=id_list,
            company=request.user.profile.company,
        )
        return Response({'rows_updated': rows_updated})

    @swagger_auto_schema(manual_parameters=batch_prospects_params)
    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticated, HasPaymentPermission],
        pagination_class=None,
    )
    def batch_prospects(self, request, pk=None):
        """
        Return the next 100 prospects with their formatted message.
        """
        campaign = self.get_object()

        if not campaign.company.has_valid_outgoing:
            return Response(
                {'detail': 'Must set valid outgoing data before sending campaign.'}, status=400)

        # We need to do some non-standard REST here by updating the sms template based on a GET
        # request. The reason for this is that we need to update the sms template and also fetch the
        # batch prospects in a single request to improve the user experience. Since the update is
        # minor, it's best to do this update here rather than cause the user to wait an extra
        # request roundtrip to update the sms template and then fetch the batch prospects.
        sms_template_id = request.query_params.get('sms_template')
        sms_category_id = request.query_params.get('sms_category')
        if sms_template_id:
            if not campaign.sms_template or int(sms_template_id) != campaign.sms_template.id:
                sms_template = SMSTemplate.objects.get(id=sms_template_id)
                campaign.sms_template = sms_template
                campaign.save(update_fields=['sms_template'])
        elif sms_category_id:
            sms_category = SMSTemplateCategory.objects.filter(
                id=sms_category_id,
                company=campaign.company,
            )
            if not sms_category.exists():
                return Response({'detail': 'Category could not be found.'}, 400)
            if not campaign.sms_template or campaign.sms_template.category_id != sms_category_id:
                campaign.sms_template = sms_category.first().first_template
                campaign.save(update_fields=['sms_template'])
        else:
            return Response(
                {'detail': 'Either a template ID or category ID is required in query params.'},
                status=400,
            )

        if campaign.sms_template and not campaign.sms_template.is_valid:
            return Response(
                {'detail': 'Invalid SMS Template, please select a valid one.'}, status=400)

        # Check if the campaign market is in a cooldown period.
        if campaign.market.current_spam_cooldown_period_end:
            cooldown = campaign.market.current_spam_cooldown_period_end
            if cooldown > timezone.now():
                return Response(
                    {'detail': 'Market is currently cooling down due to spam.'}, status=400)
            else:
                # Cooldown has passed.
                campaign.market.current_spam_cooldown_period_end = None
                campaign.market.save(update_fields=['current_spam_cooldown_period_end'])

        qs = CampaignProspect.objects.filter(
            campaign=campaign,
            scheduled=False,
            skipped=False,
            sent=False,
            prospect__phone_type='mobile',
        ).order_by(
            '-has_unread_sms',
            'sort_order',
            '-last_updated',
        ).prefetch_related(
            'campaign',
            'prospect',
            'prospect__company',
            'prospect__tags',
            'prospect__messages',
        )[:100]

        serializer = CampaignProspectSerializer(
            qs,
            many=True,
            context={
                'request': request,
                'category_id': sms_category_id,
            },
        )
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def followup(self, request, pk=None):
        """
        Creates a new followup campaign and transfers eligible campaign prospects into that
        campaign.
        """
        campaign = self.get_object()
        serializer = FollowupCampaignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.generate_note(campaign.company)

        retain_numbers = serializer.validated_data.pop('retain_numbers')
        campaign_name = serializer.validated_data.pop('campaign_name')
        followup_campaign = campaign.create_followup(
            request.user,
            campaign_name,
            retain_numbers,
        )

        CampaignNote.objects.create(
            campaign=followup_campaign,
            text=note,
        )

        if serializer.validated_data.get('responded', True):
            followup_campaign.skip_prospects_who_messaged = False
            followup_campaign.save(update_fields=['skip_prospects_who_messaged'])
        if serializer.validated_data.pop('archive_original'):
            campaign.is_archived = True
            campaign.save(update_fields=['is_archived'])
        transfer_campaign_prospects.delay(
            campaign.id,
            followup_campaign.id,
            filters=serializer.validated_data,
        )
        serializer = self.serializer_class(followup_campaign)
        return Response(serializer.data, status=201)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    @action(detail=False, methods=['get'], url_path='export')
    def export_campaigns(self, request):
        """
        Exports all campaigns under the requested users company they have access to.
        """
        filters = dict(request.query_params)
        filters['filename'] = f'campaigns_export_{timezone.now().date()}.csv'

        for f in filters:
            if isinstance(filters[f], list):
                filters[f] = filters[f][0]
            if filters[f] == 'true':
                filters[f] = True
            if filters[f] == 'false':
                filters[f] = False

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=self.request.user.profile.company,
            download_type=DownloadHistory.DownloadTypes.CAMPAIGN,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)

        return Response({'id': download.uuid})

    @swagger_auto_schema(manual_parameters=export_params)
    @action(detail=True, methods=['get'], url_path='export')
    def export_campaign_prospects(self, request, pk=None):
        """
        campaigns_export_campaign_prospects

        Export the campaign prospects as csv data filtered by lead stage id, priority or phone type.
        Supplying at least one of these query parameters is required.
        """
        campaign = self.get_object()
        lead_stage_id = request.query_params.get('lead_stage', None)
        is_priority_unread = request.query_params.get('is_priority_unread') == 'true'
        phone_type = request.query_params.get('phone_type', None)
        valid_phone_types = ['all', 'mobile', 'landline', 'other', 'litigator', 'dnc']

        # Validate the phone type if it was displayed.
        if phone_type and phone_type not in valid_phone_types:
            return Response(
                {'detail': 'Must supply valid `phone_type` as a url parameter.'},
                status=400,
                content_type="application/json",
            )

        # Make the filename and return file as response.
        if phone_type:
            export_type = phone_type
        elif is_priority_unread:
            export_type = 'priority-unread'
        elif lead_stage_id:
            try:
                export_type = LeadStage.objects.get(
                    company=request.user.profile.company,
                    id=lead_stage_id,
                ).lead_stage_title
            except LeadStage.DoesNotExist:
                return Response(
                    {'detail': 'LeadStage could not be found.'},
                    status=404,
                    content_type='application/json',
                )
        else:
            export_type = 'all'

        filename = f'{slugify(campaign.name)}_{slugify(export_type)}_{timezone.now().date()}.csv'

        filters = {
            'phone_type': phone_type,
            'lead_stage_id': lead_stage_id,
            'is_priority_unread': is_priority_unread,
            'filename': filename,
            'campaign_id': campaign.id,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=campaign.company,
            download_type=DownloadHistory.DownloadTypes.CAMPAIGN_PROSPECT,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)

        return Response({'id': download.uuid})

    @swagger_auto_schema(responses={200: "Download object UUID"})
    @action(detail=True, methods=['get'])
    def export_direct_mail_recipients(self, request, pk=None):
        """
        Export the dierct mail campaign recipients as csv data.
        """
        campaign = self.get_object()
        if not campaign.is_direct_mail:
            return Response(
                {'detail': 'Campaign is not a direct mail campaign'}, status=404,
            )
        filename = f'{slugify(campaign.name)}_recipients_{timezone.now().date()}.csv'

        filters = {
            'filename': filename,
            'campaign_id': campaign.id,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=campaign.company,
            download_type=DownloadHistory.DownloadTypes.CAMPAIGN_PROSPECT,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)

        return Response({'id': download.uuid})

    @action(detail=True, methods=['get'], serializer_class=[CampaignFullStatsSerializer,
            DirectMailCampaignStatsSerializer])
    def stats(self, request, pk=None):
        """
        Return all the main stats for the direct mail campaign.
        """
        campaign = self.get_object()
        if campaign.is_direct_mail:
            dm_campaign = DirectMailCampaign.objects.get(campaign=campaign)
            serializer = DirectMailCampaignStatsSerializer(dm_campaign.dm_campaign_stats)
        else:
            serializer = CampaignFullStatsSerializer(campaign)
        return Response(serializer.data)

    @action(detail=False, serializer_class=CampaignMinimumSerializer, pagination_class=None)
    def full(self, request, pk=None):
        """
        Return a full list of the user's company's active campaigns.
        """
        company = request.user.profile.company
        queryset = Campaign.objects.filter(company=company)
        serializer = self.serializer_class(self.filter_queryset(queryset), many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], serializer_class=CampaignIssueSerializer)
    def issues(self, request, pk=None):
        """
        Return a list of all issues the campaign has.
        """
        campaign = self.get_object()
        serializer = CampaignIssueSerializer(campaign.issues, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(method='post', responses={200: {}})
    @action(
        detail=True,
        methods=['post'],
        serializer_class=ProspectTagByCampaignSerializer,
        permission_classes=[AdminPlusModifyPermission],
    )
    def tag_prospects(self, request, pk=None):
        """
        Assigns or removes a tag based on the filters of campaigns.
        """
        campaign = self.get_object()
        company = self.request.user.profile.company

        serializer = ProspectTagByCampaignSerializer(
            data=request.data,
            context={'company': company},
        )
        serializer.is_valid(raise_exception=True)

        prospects = list(set(Prospect.objects.filter(
            campaignprospect__campaign=campaign,
        ).values_list('pk', flat=True)))

        add_tags = serializer.validated_data.get('add', [])
        remove_tags = serializer.validated_data.get('remove', [])

        if prospects:
            if add_tags:
                handle_prospect_tag_update(
                    user_id=request.user.id,
                    prospect_id=prospects,
                    toggles={'tags': add_tags},
                    is_adding=True,
                )
            if remove_tags:
                handle_prospect_tag_update(
                    user_id=request.user.id,
                    prospect_id=prospects,
                    toggles={'tags': remove_tags},
                    is_adding=False,
                )

        return Response()

    @swagger_auto_schema(methods=['post', 'delete'], responses={200: CampaignSerializer})
    @action(
        detail=True,
        methods=['post', 'delete'],
        serializer_class=ModifyCampaignTagsSerializer,
        permission_classes=[IsAuthenticated],
    )
    def tags(self, request, pk=None):
        """
        post: Associate tags to a campaign.
        delete: Remove tags from a campaign.
        """
        campaign = self.get_object()
        company = self.request.user.profile.company
        serializer = ModifyCampaignTagsSerializer(data=request.data, context={'company': company})
        serializer.is_valid(raise_exception=True)

        if request.method == 'POST':
            campaign.tags.add(*request.data['tags'])
        else:
            campaign.tags.remove(*request.data['tags'])

        response_serializer = CampaignSerializer(campaign)
        return Response(response_serializer.data)

    @swagger_auto_schema(
        method='get',
        responses={200: DMCampaignListProspectsSerializer},
    )
    @action(detail=True, methods=['get'], pagination_class=SherpaPagination)
    def get_direct_mail_campaign_recipients(self, request, pk=None):
        """
        Returns campaign id, campaign name and direct mail campaign recipients list.
        """
        campaign = self.get_object()
        if not campaign.is_direct_mail:
            return Response(
                {'detail': 'Campaign is not a direct mail campaign'}, status=404,
            )
        page_size = int(request.query_params.get('page_size', 100))
        self.pagination_class.page_size = page_size

        address_lookup = Case(
            When(
                prop__mailing_address__address__isnull=False,
                then=F('prop__mailing_address__address'),
            ),
            default=F('prop__address__address'),
            output_field=CharField(),
        )
        city_lookup = Case(
            When(
                prop__mailing_address__city__isnull=False,
                then=F('prop__mailing_address__city'),
            ),
            default=F('prop__address__city'),
            output_field=CharField(),
        )
        state_lookup = Case(
            When(
                prop__mailing_address__state__isnull=False,
                then=F('prop__mailing_address__state'),
            ),
            default=F('prop__address__state'),
            output_field=CharField(),
        )
        zip_code_lookup = Case(
            When(
                prop__mailing_address__zip_code__isnull=False,
                then=F('prop__mailing_address__zip_code'),
            ),
            default=F('prop__address__zip_code'),
            output_field=CharField(),
        )
        if request.user.profile.company.enable_dm_golden_address:
            address_lookup = Case(
                When(
                    prop__skiptraceproperty__returned_address_1__isnull=False,
                    then=F('prop__skiptraceproperty__returned_address_1'),
                ),
                default=address_lookup,
                output_field=CharField(),
            )
            city_lookup = Case(
                When(
                    prop__skiptraceproperty__returned_city_1__isnull=False,
                    then=F('prop__skiptraceproperty__returned_city_1'),
                ),
                default=city_lookup,
                output_field=CharField(),
            )
            state_lookup = Case(
                When(
                    prop__skiptraceproperty__returned_state_1__isnull=False,
                    then=F('prop__skiptraceproperty__returned_state_1'),
                ),
                default=state_lookup,
                output_field=CharField(),
            )
            zip_code_lookup = Case(
                When(
                    prop__skiptraceproperty__returned_zip_1__isnull=False,
                    then=F('prop__skiptraceproperty__returned_zip_1'),
                ),
                default=zip_code_lookup,
                output_field=CharField(),
            )

        query = request.query_params.get('query', '')
        queryset = campaign.prospects.annotate(
            fullname=Case(
                When(
                    first_name__isnull=True,
                    then=None,
                ),
                default=Concat('first_name', Value(' '), 'last_name', output_field=CharField()),
                output_field=CharField(),
            ),
            campaign_count=Count('campaignprospect', distinct=True),
            property_tags_length=Count('prop__tags', distinct=True),
            property_tags=ArrayAgg(F('prop__tags'), distinct=True, filter=~Q(prop__tags=None)),
            prospect_tags_length=Count('do_not_call', filter=Q(do_not_call=True), distinct=True) + Count('is_blocked', filter=Q(is_blocked=True), distinct=True) + Count('is_priority', filter=Q(is_priority=True), distinct=True) + Count('is_qualified_lead', filter=Q(is_qualified_lead=True), distinct=True) + Count('wrong_number', filter=Q(wrong_number=True), distinct=True),  # noqa E501
            address=address_lookup,
            city=city_lookup,
            state=state_lookup,
            zip_code=zip_code_lookup,
            # We will get duplicated rows if a prop has more than 1 skiptraceproperty, with this we
            # can get them enumerated in such a way that we can filter and keep only the newer one
            skiptraceproperty_rank=Window(
                expression=DenseRank(),
                partition_by=[F('prop__pk')],
                order_by=F('prop__skiptraceproperty__created').desc(),
            ),
        ).values(
            'id', 'fullname', 'address', 'campaign_count', 'property_tags_length', 'property_tags',
            'prospect_tags_length', 'do_not_call', 'is_blocked', 'is_priority', 'is_qualified_lead',
            'wrong_number', 'city', 'state', 'zip_code', 'phone_raw', 'skiptraceproperty_rank',
        )

        # TODO: This is really heavy for the db, will have to be changed to use elasticsearch
        if query:
            queryset = queryset.filter(
                Q(fullname__icontains=query) |
                Q(address__icontains=query) |
                Q(phone_raw__icontains=query),
            )
        queryset = queryset.order_by(
            request.query_params.get('ordering', '-id'),
            '-prop__skiptraceproperty__created',
        )

        # Django doesn't allow to filter by the result of a Window function, so we have to wrap
        # the queryset's query so we can actually do that
        sql, params = queryset.query.sql_with_params()
        queryset = Prospect.objects.raw("""
            SELECT * FROM ({}) prospects_with_ranked_skiptraceproperties
            WHERE skiptraceproperty_rank IS NULL OR skiptraceproperty_rank = 1
            """.format(sql),
            [*params],
        )

        page = self.paginate_queryset(queryset)
        campaign_dict_data = {'campaign_id': pk, 'campaign_name': campaign.name}
        serializer = DMCampaignListProspectsSerializer(page, many=True)
        response = self.get_paginated_response(serializer.data)
        response.data.update(campaign_dict_data)
        return response

    @swagger_auto_schema(
        method='patch',
        request_body=RemoveDMCampaignRecipientsSerializer,
        responses={200: {}},
    )
    @action(detail=True, methods=['patch'])
    def remove_direct_mail_campaign_recipients(self, request, pk=None):
        """
        Remove direct mail campaign recipients.
        Input Parameters:
            action (str): remove.
            prospect_ids (list): list of prospect ids.
        Returns:
            Json Response : {}.
        """
        campaign = self.get_object()
        _ = get_object_or_404(DirectMailCampaign, campaign=campaign)
        serializer = RemoveDMCampaignRecipientsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prospect_ids = serializer.validated_data.get('prospect_ids')
        campaign_prospect_qs = campaign.campaignprospect_set.filter(prospect_id__in=prospect_ids)
        campaign_prospect_qs.update(
            removed_datetime=timezone.now(),
            removed_by=request.user.profile,
        )
        prop_ids = campaign_prospect_qs\
            .values_list('prospect__prop_id', flat=True)\
            .order_by('prospect__prop_id')\
            .distinct('prospect__prop_id')
        stacker_full_update(prospect_ids, prop_ids)
        return Response({}, status=200)

    @action(detail=False, methods=['post'])
    def get_cp_details_queryset(self, request):
        data = request.data
        ids = data['ids']
        if len(ids) > 0:
            queryset = Campaign.objects.filter(pk__in=ids)
            serializer = self.serializer_class(self.filter_queryset(queryset), many=True)
            return Response(serializer.data)
        else:
            return Response(
                {'detail': 'Campaign IDs list is empty'}, status=400,
            )


class UploadProspectViewSet(CompanyAccessMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):
    serializer_class = UploadProspectsSerializer
    pagination_class = CursorPagination
    filterset_fields = ('campaign',)
    model = UploadProspects

    def list(self, request):
        """
        Limit to non-setup instances when listing.

        Note: We can't do this in get queryset as we need to access those instances in other
        actions.
        """
        page_size = int(request.query_params.get('page_size', 25))
        queryset = self.filter_queryset(
            self.get_queryset().exclude(status=UploadBaseModel.Status.SETUP),
        )
        self.pagination_class.page_size = page_size
        self.pagination_class.ordering = "-id"
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            # We need count, however it doesn't come with `CursorPagination` by default.
            response.data['count'] = queryset.count()
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        responses={201: UploadProspectsResponseSerializer},
        request_body=UploadProspectsRequestSerializer,
    )
    @action(detail=False, methods=['post'])
    def map_fields(self, request):
        """
        campaigns_map_fields

        Map fields from FlatFile data response.

        request must have the following:
        `headers_matched`: list of headers matched in Flatfile
        `valid_data`: valid data returned from Flatfile
        `uploaded_filename`: original name of file uploaded
        `campaign`: pk of `Campaign` object user is uploading to

         The following are optional:
        `confirm_additional_cost`: Boolean - user confirmed to pay additional cost if required
        `id`: Key to an `UploadProspect` object. Will only have this if confirming additional cost.
        """
        headers_matched = request.data.get('headers_matched', [])
        data = request.data.get('valid_data', [])
        filename = request.data.get('uploaded_filename')
        campaign_pk = request.data.get('campaign')
        upload_prospect_id = request.data.get('id', None)
        confirm_additional_cost = request.data.get('confirm_additional_cost', False)
        campaign_type = request.data.get('campaign_type', 'sms')

        # Check that we have the data needed before mapping.
        if not (headers_matched and data and filename):
            data = {
                'detail': 'Must send `headers_matched`, `valid_data`, `uploaded_filename` in'
                          ' request.',
            }
            return Response(data, status=400)

        # Using get_object_or_404 because the`UploadProspect` object hasn't been created yet so
        # we can't get the `Campaign` from the `UploadProspect` object.
        campaign = get_object_or_404(Campaign, pk=campaign_pk) if campaign_pk else None
        csv_mapper = CSVFieldMapper(request, upload_prospect_id)
        csv_mapper.map_upload_prospect(campaign, confirm_additional_cost, campaign_type)

        if csv_mapper.success or csv_mapper.exceeds_count:
            data = {
                'id': csv_mapper.upload_object.id,
                'total_rows': csv_mapper.upload_object.total_rows,
                'duplicated_rows': csv_mapper.upload_object.duplicated_prospects,
                'uploaded_filename': csv_mapper.upload_object.uploaded_filename,
            }
            if campaign:
                data.update({
                    'campaign': csv_mapper.upload_object.campaign.id,
                    'confirm_additional_cost': confirm_additional_cost,
                    'cost': csv_mapper.additional_cost,
                    'exceeds_count': csv_mapper.upload_object.exceeds_count,
                })

            return Response(data, 201)

        return Response({'detail': 'Failed to map columns.'}, status=400)

    @swagger_auto_schema(responses={200: {}}, manual_parameters=start_upload_params)
    @action(detail=True, methods=['get'])
    def start_upload(self, request, pk=None):
        """
        Start uploading prospects to campaign.
        """
        upload_prospects_record = get_object_or_404(UploadProspects, pk=pk)
        if request.query_params.get('campaign'):
            campaign = get_object_or_404(Campaign, pk=int(request.query_params.get('campaign')))
            upload_prospects_record.campaign = campaign
            upload_prospects_record.save(update_fields=['campaign'])
        else:
            campaign = upload_prospects_record.campaign

        # Look to see if there's a value in additional_upload_cost_amount.
        if upload_prospects_record.additional_upload_cost_amount > 0:
            # Charge additional cost.
            upload_prospects_record.transaction = Transaction.authorize(
                campaign.company,
                'Sherpa Upload Fee',
                upload_prospects_record.additional_upload_cost_amount,
            )
            upload_prospects_record.save(update_fields=['transaction'])
            if not upload_prospects_record.transaction.is_authorized:
                # Authorized failed, return reason in response.
                data = {'detail': 'Could not process upload, your payment method was declined.'}
                return Response(data, status=402)

        tag_ids = request.query_params.get('tags')
        tag_ids = tag_ids.split(",") if tag_ids else []
        try:
            tag_ids = [int(tag_id) for tag_id in tag_ids]
        except ValueError:
            data = {'tags': ["Tags must be integers."]}
            return Response(data, 400)
        company_tag_ids = upload_prospects_record.company.propertytag_set.filter(
            pk__in=tag_ids).values_list('pk', flat=True)
        missing_company_tag_ids = set(tag_ids) - set(company_tag_ids)
        if missing_company_tag_ids:
            data = {'tags': [f"Tags {missing_company_tag_ids} do not exist in the Company."]}
            return Response(data, 400)
        upload_prospects_task2.delay(upload_prospects_record.pk, tag_ids)
        return Response({})

    @action(detail=True, methods=['patch', 'delete'])
    def tag(self, request, pk=None):
        """
        Updates all properties created via the upload with the new tags.
        """
        serializer = StackerSinglePropertyTagSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.get_object()
        id_list = list(instance.property_set.values_list('id', flat=True))
        if request.method == 'PATCH':
            assignments = [
                PropertyTagAssignment(
                    tag_id=tag_id,
                    prop_id=prop_id,
                )
                for tag_id in serializer.validated_data.get("tags")
                for prop_id in id_list
            ]
            PropertyTagAssignment.objects.bulk_create(assignments, ignore_conflicts=True)
        else:
            PropertyTagAssignment.objects.filter(
                Q(prop_id__in=id_list) & Q(tag_id__in=serializer.validated_data.get("tags")),
            ).delete()

        prepare_tags_for_index_update.delay(id_list)
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)

        return Response(serializer.data, 200)


class CampaignNoteViewSet(CreatedByMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = CampaignNoteSerializer
    filterset_fields = ('campaign',)
    expandable_fields = ('created_by',)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def get_queryset(self):
        """
        Limit to campaigns that belong to the user's company.
        """
        return CampaignNote.objects.filter(campaign__company=self.request.user.profile.company)


class StatsBatchViewSet(ListModelMixin, GenericViewSet):
    """
    Endpoint to work with stats batches for campaigns

    list: Return the stats batches for a campaign. Must supply the `campaign` in query parameter.
    """
    permission_classes = (IsAuthenticated,)
    filterset_fields = ('campaign',)
    serializer_class = StatsBatchSerializer

    def get_queryset(self):
        """
        Filter to only the campaigns of the user's company.
        """
        return StatsBatch.objects.filter(campaign__company=self.request.user.profile.company)

    def list(self, request, *args, **kwargs):
        # Require query parameter to define campaign
        if not request.query_params.get('campaign'):
            raise ValidationError('Must supply `campaign` in query parameter.')
        return super().list(request, *args, **kwargs)


class CampaignTagViewSet(CompanyAccessMixin, ModelViewSet):
    model = CampaignTag
    serializer_class = CampaignTagSerializer
    pagination_class = None
    permission_classes = [IsAuthenticated, AdminPlusModifyPermission]

    def perform_create(self, serializer):
        """
        Save the request user's company as the tag's company.
        """
        serializer.save(company=self.request.user.profile.company)
