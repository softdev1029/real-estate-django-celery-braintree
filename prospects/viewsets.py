from drf_yasg.utils import no_body, swagger_auto_schema
from pytz import timezone

from django.conf import settings
from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
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
from campaigns.serializers import CampaignSerializer
from campaigns.tasks import attempt_batch_text
from campaigns.utils import push_to_campaign
from companies.models import DownloadHistory
from companies.tasks import generate_download
from core.mixins import CompanyAccessMixin, CreatedByMixin
from phone.choices import Provider
from prospects.utils import record_phone_number_opt_outs
from sherpa.docs import expandable_query_parameters
from sherpa.models import (
    Activity,
    Campaign,
    CampaignProspect,
    LeadStage,
    LitigatorReportQueue,
    Note,
    PhoneNumber,
    Prospect,
    UserProfile,
)
from sherpa.permissions import (
    AdminPlusModifyPermission,
    HasPaymentPermission,
    StaffPlusModifyPermission,
)
from sherpa.serializers import EmptySerializer
from sherpa.tasks import sherpa_send_email
from sms import TELNYX_ERRORS_FULL
from sms.serializers import QuickReplySerializer, SMSMessageSerializer
from sms.utils import handle_telnyx_view_error, telnyx_error_has_error_code
from .docs import (
    campaign_prospect_query_parameters,
    export_prospect_params,
    general_id_list_param,
    prospect_uuid_token,
    search_parameters,
    unread_parameters,
)
from .filters import CampaignProspectFilter
from .models import ProspectRelay, ProspectTag
from .permissions import CustomTagModify
from .serializers import (
    AssignNumberSerializer,
    BatchSendRequestSerializer,
    BulkActionResponseSerializer,
    CampaignProspectBulkActionSerializer,
    CampaignProspectSerializer,
    CampaignProspectUnreadSerializer,
    CloneProspectSerializer,
    ProspectActivitySerializer,
    ProspectCRMActionSerializer,
    ProspectNoteSerializer,
    ProspectPushToCampaignSerializer,
    ProspectRelayConnectSerializer,
    ProspectRelaySerializer,
    ProspectReminderSerializer,
    ProspectSendMessageSerializer,
    ProspectSerializer,
    ProspectTagSerializer,
    PublicProspectSerializer,
    UnreadMessagesSerializer,
)
from .utils import is_empty_search, ProspectSearch


class ProspectViewSet(
        CompanyAccessMixin,
        ListModelMixin,
        RetrieveModelMixin,
        UpdateModelMixin,
        GenericViewSet):
    model = Prospect
    permission_classes = (IsAuthenticated, HasPaymentPermission)
    pagination_class = CursorPagination
    serializer_class = ProspectSerializer
    filter_backends = (SearchFilter, OrderingFilter)
    expandable_fields = ('campaigns', 'campaign_prospects', 'agent')
    ordering = ('-id',)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """
        Run extra functions if needed for certain `Prospect` fields before continuing with update.
        """
        serializer = None
        instance = self.get_object()
        update_functions = {
            'is_qualified_lead': instance.toggle_qualified_lead,
            'is_priority': instance.toggle_is_priority,
            'owner_verified_status': instance.toggle_owner_verified,
            'do_not_call': instance.toggle_do_not_call,
            'wrong_number': instance.toggle_wrong_number,
        }

        for field_name in request.data:
            if field_name in update_functions:
                value = request.data[field_name]
                updated_instance, activities = update_functions[field_name](request.user, value)
                updated_instance.activities = activities
                serializer = self.serializer_class(updated_instance)

        if serializer:
            return Response(serializer.data)

        if 'tags' in request.data and instance.prop:
            add = set(request.data.pop('tags'))
            instance.prop.tags.add(*add)

            current = set(instance.prop.tags.values_list('pk', flat=True))
            remove = current ^ add
            instance.prop.tags.remove(*remove)
        return super().partial_update(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[export_prospect_params, general_id_list_param])
    @action(
        detail=False,
        methods=['get'],
        pagination_class=None,
        filter_backends=[SearchFilter],
        permission_classes=[IsAuthenticated],
    )
    def export(self, request):
        """
        CSV Export a list of prospects.
        """
        # Get queryset from the search results.
        filename = f'leadsherpa-prospects_{dj_timezone.now().date()}.csv'
        ids = []
        if request.query_params.get('ids', None):
            ids = [int(i) for i in request.query_params.get('ids') if i.strip().isdigit()]

        filters = {
            'search_input': request.query_params.get('search', '*'),
            'extra': request.query_params,
            'filename': filename,
            'ids': ids,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=request.user.profile.company,
            download_type=DownloadHistory.DownloadTypes.PROSPECT,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        if is_empty_search(request.query_params) and settings.EMAIL_ADMIN_ON_FULL_EXPORT:
            # If the user has performed a full export, we want to alert the success manager as it's
            # an indicator for potential churn.
            sherpa_send_email.delay(
                f'{request.user.profile.company.name} has performed a full export',
                'email/companies/full_prospect_download_alert.html',
                settings.SUCCESS_ADMIN_EMAIL,
                {
                    'company_name': request.user.profile.company.name,
                    'user_email': request.user.email,
                    'user_full_name': request.user.get_full_name(),
                },
            )

        generate_download.delay(download.uuid)

        return Response({'id': download.uuid})

    @swagger_auto_schema(responses={200: CampaignSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def campaigns(self, request, pk=None):
        """
        Return the list of campaigns that the prospect is in.
        """
        prospect = self.get_object()
        queryset = prospect.campaign_qs.all()
        serializer = CampaignSerializer(queryset, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(responses={201: {}})
    @action(detail=True, methods=['post'], serializer_class=ProspectPushToCampaignSerializer)
    def push_to_campaign(self, request, pk=None):
        """
        Return the list of campaigns that the prospect is in.
        """
        prospect = self.get_object()
        campaign_pk = request.data.get('campaign')
        tags = request.data.get('tags', [])
        campaign = get_object_or_404(Campaign, pk=campaign_pk)
        remaining_uploads = prospect.company.upload_count_remaining_current_billing_month
        charge = push_to_campaign(campaign, prospect, tags)

        if charge and not remaining_uploads and not prospect.company.is_billing_exempt:
            transaction = Transaction.authorize(
                campaign.company,
                'Sherpa Upload Fee',
                charge * prospect.company.cost_per_upload,
            )
            transaction.charge()

        return Response({}, status=201)

    @swagger_auto_schema(responses={200: SMSMessageSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        """
        Get the messages associated with a given prospect.
        """
        prospect = self.get_object()
        sms_qs = prospect.messages.order_by('dt')
        serializer = SMSMessageSerializer(sms_qs, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=search_parameters,
        responses={200: ProspectSerializer(many=True)},
    )
    @action(
        detail=False,
        methods=['get'],
        serializer_class=ProspectSerializer,
        permission_classes=[IsAuthenticated],
    )
    def search(self, request):
        """
        Search for matching `Prospects`.

        search: the string we are searching for (* to search all)
        lead_stage: ID for a `LeadStage`, is_priority', or 'is_qualified_lead' (0 to search all)
        Leaving the above parameters blank searches all

        Note: A newer search endpoint has been added - prospect_search.  We are keeping this
        endpoint active for mobile.  We will probably switch the prospect_search endpoint to this
        endpoint when mobile catches up.
        """
        search_input = request.query_params.get('search', '*')
        page_size = int(request.query_params.get('page_size', 100))

        search = ProspectSearch(search_input, request.user, request.query_params)
        search.search()
        queryset = search.result

        self.pagination_class.page_size = page_size
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            # We need count, however it doesn't come with `CursorPagination` by default.
            response.data['count'] = queryset.count()
            return response

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def set_reminder(self, request, pk=None):
        """
        Set a reminder to be sent to the user to followup with a prospect.
        """
        serializer = ProspectReminderSerializer(
            data=request.data,
            context={'company': request.user.profile.company})
        serializer.is_valid(raise_exception=True)

        prospect = self.get_object()

        agent = UserProfile.objects.get(pk=serializer.validated_data.get('agent'))

        tz = prospect.company.timezone
        prospect.has_reminder = True
        prospect.reminder_email_sent = False
        prospect.reminder_date_utc = serializer.validated_data.get('time')
        prospect.reminder_date_local = prospect.reminder_date_utc.astimezone(timezone(tz))
        prospect.reminder_timezone = tz
        prospect.reminder_agent = agent
        prospect.save()
        serializer = self.serializer_class(prospect)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def remove_reminder(self, request, pk=None):
        """
        Remove a reminder for a prospect that was previously set.
        """
        prospect = self.get_object()
        prospect.has_reminder = False
        prospect.reminder_email_sent = False
        prospect.reminder_date_utc = None
        prospect.reminder_date_local = None
        prospect.reminder_timezone = None
        prospect.reminder_agent = None
        prospect.save()
        serializer = self.serializer_class(prospect)
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: {}})
    @action(
        detail=True,
        methods=['post'],
        serializer_class=ProspectSendMessageSerializer,
        permission_classes=[StaffPlusModifyPermission],
    )
    def send_message(self, request, pk=None):
        """
        Send an individual message to a prospect.
        """
        serializer = ProspectSendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = self.get_object()
        if instance.opted_out:
            return Response(
                status=400,
                data={'detail': 'Prospect has opted-out of the conversation'},
            )

        # Do not allow agent to send a message if the prospect has no valid number assigned
        # and the market does not have sufficient numbers.
        cp = instance.campaignprospect_set.select_related('campaign__market').filter(
            campaign__market__isnull=False).first()
        is_invalid = cp is None or all([
            not instance.has_valid_sherpa_number,
            not cp.campaign.market.bulk_phone_numbers.count(),
        ])
        if is_invalid:
            return Response(
                status=400,
                data={'detail': 'No active numbers in market.'},
            )

        try:
            instance.send_message(request.data.get('message'), request.user)
        except TELNYX_ERRORS_FULL as e:
            if telnyx_error_has_error_code(e, '40300'):
                # Stop rule triggered.
                record_phone_number_opt_outs(
                    instance.phone_raw,
                    instance.sherpa_phone_number_obj.phone,
                )

            # Handle the telynx error, there probably will be a few different cases here.
            return handle_telnyx_view_error(e)

        return Response({})

    @swagger_auto_schema(
        responses={200: ProspectActivitySerializer},
        request_body=ProspectCRMActionSerializer,
    )
    @action(detail=True, methods=['post'])
    def push_to_zapier(self, request, pk=None):
        """
        Push the prospect data to Zapier if the webhook is setup.
        """
        prospect = self.get_object()
        if prospect.pushed_to_zapier:
            return Response({'detail': 'Prospect already pushed to Zapier.'}, status=400)

        campaign_id = request.data.get('campaign')
        if not campaign_id:
            return Response(
                {'detail': '`campaign` is required in the request payload.'},
                status=400,
            )

        campaign = get_object_or_404(Campaign, id=campaign_id)
        if not campaign.zapier_webhook:
            message = (f'Campaign "{campaign.name}" does not have a zapier webhook.')
            return Response({'detail': message}, status=400)

        campaign_prospect = get_object_or_404(
            CampaignProspect, prospect=prospect, campaign=campaign)

        try:
            campaign_prospect.push_to_zapier(request.user)
        except Exception:
            return Response({'detail': 'Could not push prospect to Zapier'}, 400)

        activities = prospect.latest_crm_activities
        serializer = ProspectActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        responses={200: ProspectActivitySerializer},
        request_body=ProspectCRMActionSerializer,
    )
    @action(detail=True, methods=['post'])
    def email_to_podio(self, request, pk=None):
        """
        Sends an email which if the user has it setup will create an item in podio from the data
        sent via email.
        """
        # Verify the prospect data is correct
        prospect = self.get_object()
        if prospect.emailed_to_podio:
            return Response({'detail': 'Prospect already emailed to Podio.'}, status=400)

        required_fields = [
            ('first name', prospect.first_name),
            ('last name', prospect.last_name),
            ('address', prospect.property_address),
            ('city', prospect.property_city),
            ('state', prospect.property_state),
            ('phone', prospect.phone_display),
        ]
        for field_tuple in required_fields:
            if field_tuple[1] is None:
                return Response(
                    {'detail': f"Prospect does not have a valid data. Missing '{field_tuple[0]}'"},
                    status=400,
                )

        # Verify that the campaign is available for emailing to podio
        campaign_id = request.data.get('campaign')
        if not campaign_id:
            return Response(
                {'detail': '`campaign` is required in the request payload.'},
                status=400,
            )

        campaign = get_object_or_404(Campaign, id=campaign_id)
        if not campaign.podio_push_email_address:
            message = (f'Campaign "{campaign.name}" does not have a podio email.')
            return Response({'detail': message}, status=400)

        campaign_prospect = get_object_or_404(
            CampaignProspect, prospect=prospect, campaign=campaign)

        try:
            campaign_prospect.send_podio_email(request.user)
        except Exception:
            return Response({'detail': 'Could not email prospect to Podio'}, 400)

        activities = prospect.latest_crm_activities
        serializer = ProspectActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        responses={200: None},
        request_body=no_body,
    )
    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        """
        Mark all the messages from the prospect as read.
        """
        prospect = self.get_object()
        prospect.mark_as_read()
        return Response({})

    @action(detail=True, methods=['get'], serializer_class=QuickReplySerializer)
    def quick_replies(self, request, pk=None):
        """
        Get quick replies filled in with data from a `Prospect`
        """
        quick_replies = self.get_object().prefill_text_list
        serializer = QuickReplySerializer(quick_replies, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[prospect_uuid_token],
        responses={'200': PublicProspectSerializer},
    )
    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def public(self, request, pk=None):
        """
        prospects_public

        Return the prospect's data that is displayed on their public page.

        Note: There is a bug in the docs package and the below `id` path parameter can not be
        removed at this time, however only the `token` param is needed/valid.
        """
        # This is called the public page, however it uses a non-public uuid token, it's basically
        # public if you have the token. Users use this to send the prospect conversation to other
        # people that are going to follow-up.
        try:
            prospect = Prospect.objects.get(token=pk)
        except Prospect.DoesNotExist:
            # Need to allow for token or id temporarily, as some public urls were sent with id.
            prospect = get_object_or_404(Prospect, id=pk)
        serializer = PublicProspectSerializer(prospect)
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: ProspectSerializer})
    @action(detail=True, methods=['post'], serializer_class=CloneProspectSerializer)
    def clone(self, request, pk=None):
        """
        Clone a campaign prospect and return the newly created in the response data.
        """
        company = request.user.profile.company
        clone_serializer = CloneProspectSerializer(data=request.data, context={'company': company})
        clone_serializer.is_valid(raise_exception=True)

        # Cloned prospect data is valid, now time to create the new data.
        campaign_id = clone_serializer.validated_data.get('campaign')
        original_prospect = self.get_object()

        # Validate that the campaign prospect exists for the passed in campaign.
        try:
            original_campaign_prospect = original_prospect.campaignprospect_set.get(
                campaign_id=campaign_id)
        except CampaignProspect.DoesNotExist:
            return Response(
                {'detail': f'Campaign does not exist for campaign {campaign_id}'},
                status=400,
            )

        new_cp = original_campaign_prospect.clone(clone_serializer.validated_data)
        serializer = CampaignProspectSerializer(new_cp)
        return Response(serializer.data, status=201)

    @swagger_auto_schema(responses={200: ProspectActivitySerializer(many=True)})
    @action(detail=True, methods=['get'])
    def activities(self, request, pk=None):
        """
        Return a list of the prospect's activity records.
        """
        prospect = self.get_object()
        activities = prospect.activity_set.all()
        serializer = ProspectActivitySerializer(activities, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(methods=['patch', 'patch'])
    @action(detail=True, methods=['patch', 'post'], serializer_class=AssignNumberSerializer)
    def assign_number(self, request, pk=None):
        """
        prospect-assign_number

        post: Assign a sherpa phone number to a prospect.

              If passing in the `force_assign` property in the payload, then it will disassociate
              the prospect with their current sherpa number and assign a new one.

        patch: DEPRECATED: Should use POST for this action in favor of PATCH. Frontend is still
               using patch but needs to be switched to post.
        """
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        force_assign = serializer.validated_data.get('force_assign')
        campaign_id = serializer.validated_data.get('campaign_id')

        prospect = self.get_object()
        serializer = ProspectSerializer(prospect)

        #  Locate the campaign prospect.
        campaign = None
        if campaign_id:
            try:
                campaign = Campaign.objects.get(
                    id=campaign_id,
                    company=request.user.profile.company,
                )
            except Campaign.DoesNotExist:
                return Response(
                    {'detail': f'Campaign could not be found with campaign {campaign_id}'},
                    status=400,
                )
        else:
            campaign = prospect.campaign_qs.filter(market__isnull=False).first()

        if not campaign:
            return Response(
                {'detail': 'Campaign could not be found.'},
                status=400,
            )

        campaign_prospect = CampaignProspect.objects.get(prospect=prospect, campaign=campaign)

        status_code = 304
        main_check = any([
            force_assign,
            not prospect.sherpa_phone_number_obj,
            (
                prospect.sherpa_phone_number_obj and  # noqa W504
                prospect.sherpa_phone_number_obj.status == PhoneNumber.Status.RELEASED
            ),
        ])
        if main_check:
            market = campaign_prospect.campaign.market
            if not market.bulk_phone_numbers:
                return Response({
                    'detail': f'Market {market.name} does not have any available phone numbers.',
                }, status=400)
            campaign_prospect.assign_number()
            status_code = 200

        return Response(serializer.data, status=status_code)

    @action(detail=True, methods=['post'])
    def report(self, request, pk=None):
        """
        Reports a prospect as a possible litigator for Sherpa staff to investigate.

        Automatically sets the prospect as a DNC.
        """
        prospect = self.get_object()
        LitigatorReportQueue.submit(prospect=prospect, user=request.user)

        #  Regardless of the action above, set this prospect to DNC and block.
        _, activities = prospect.toggle_do_not_call(request.user, True)
        prospect.is_blocked = True
        prospect.save(update_fields=['is_blocked'])
        prospect.activities = activities
        serializer = self.serializer_class(prospect)
        return Response(serializer.data, status=201)


class ProspectNoteViewSet(CreatedByMixin, ModelViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = ProspectNoteSerializer
    filterset_fields = ('prospect',)
    expandable_fields = ('created_by',)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        """
        Save the request user as the `created_by` user and create a new activity for the prospect.
        """
        note = serializer.save(created_by=self.request.user)
        Activity.objects.create(
            prospect=note.prospect,
            title=Activity.Title.CREATED_NOTE,
            icon="fa fa-plus-circle",
            description=f"{self.request.user.get_full_name()} added a note",
        )

    def get_queryset(self):
        """
        Limit to prospects that belong to the user's company.
        """
        return Note.objects.filter(prospect__company=self.request.user.profile.company)


class CampaignProspectViewSet(RetrieveModelMixin, ListModelMixin, CreateModelMixin,
                              UpdateModelMixin, GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = CampaignProspectSerializer
    filterset_class = CampaignProspectFilter
    expandable_fields = ('campaign',)

    @swagger_auto_schema(manual_parameters=[
        campaign_prospect_query_parameters,
        expandable_query_parameters(expandable_fields),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(manual_parameters=[expandable_query_parameters(expandable_fields)])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def get_queryset(self):
        """
        Limit to the campaign prospects of the campaign company.

        Also handles the filter of `is_priority_unread` if that query filter was passed in.
        """
        queryset = CampaignProspect.objects.filter(
            prospect__company=self.request.user.profile.company.id)

        is_priority_unread = self.request.query_params.get('is_priority_unread', None)
        if is_priority_unread == 'true':
            queryset = queryset.filter(
                Q(prospect__is_priority=True) | Q(prospect__has_unread_sms=True),
            )
        sort_date = 'prospect__last_sms_received_utc'
        # There is a special filter for "Initial Message Sent" that we need to filter to sent.
        lead_stage_param = self.request.query_params.get('lead_stage', None)
        if lead_stage_param:
            try:
                lead_stage = LeadStage.objects.get(id=lead_stage_param)
                if lead_stage.lead_stage_title == 'Initial Message Sent':
                    queryset = queryset.filter(sent=True)
                    # Change sort date to sent date since we haven't gotten a response yet.
                    sort_date = 'prospect__last_sms_sent_utc'
            except LeadStage.DoesNotExist:
                pass

        return queryset.order_by(
            '-has_unread_sms',
            F(sort_date).desc(nulls_last=True),
        )

    @swagger_auto_schema(responses={200: CampaignProspectSerializer})
    @action(detail=True, methods=['post'], serializer_class=CloneProspectSerializer)
    def clone(self, request, pk=None):
        """
        campaign-prospects_clone

        Clone a campaign prospect and return the newly created in the response data.

        DEPRECATED 20200420 - Moving the clone logic to the Prospect endpoint as the frontend does
        not always have the campaign prospect when it is cloning a prospect.
        """
        company = request.user.profile.company
        clone_serializer = CloneProspectSerializer(data=request.data, context={'company': company})
        clone_serializer.is_valid(raise_exception=True)

        # Cloned prospect data is valid, now time to create the new data.
        original_cp = self.get_object()
        new_cp = original_cp.clone(request.data)
        serializer = CampaignProspectSerializer(new_cp)
        return Response(serializer.data, status=201)

    @swagger_auto_schema(
        method='post',
        responses={200: EmptySerializer},
    )
    @action(
        detail=True,
        methods=['post'],
        permission_classes=[StaffPlusModifyPermission],
        serializer_class=BatchSendRequestSerializer,
    )
    def batch_send(self, request, pk=None):
        """
        Attempt to send a bulk message to the campaign prospect (will be sent or skipped).
        """
        campaign_prospect = self.get_object()
        campaign = campaign_prospect.campaign
        market = campaign.market

        if market.total_intial_sms_sent_today_count > market.total_initial_send_sms_daily_limit:
            return Response({'detail': "Daily limit has been reached"}, status=400)

        if not campaign.sms_template:
            return Response(status=400, data={
                'detail': f'Campaign `{campaign.name}` does not have an assigned SMS Template.',
            })

        if campaign.company.is_messaging_disabled:
            return Response(status=400, data={
                'detail': 'Messaging is currently disabled in your timezone.',
            })

        # Action payload gives the frontend a way to send an extra action to the send request.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action = serializer.validated_data.get('action', None)
        default_template_id = campaign_prospect.sms_template_id if campaign_prospect.\
            sms_template_id else campaign.sms_template_id
        template_id = serializer.validated_data.get('template', default_template_id)
        force_skip = action == 'skip'

        update_fields = []
        prospect = campaign_prospect.prospect
        if action == 'dnc':
            prospect.do_not_call = True
            update_fields.append('do_not_call')

        # Assign agent if none has been assigned.
        if not prospect.agent:
            prospect.agent = request.user.profile
            update_fields.append('agent')

        if update_fields:
            prospect.save(update_fields=update_fields)

        # Need to update sent on the campaign prospect so that the `total_initial_sent_skipped` is
        # incremented properly in the campaign prospect save hook, and the data is updated
        # immediately rather than in the delayed task.
        campaign_prospect.sent = True
        campaign_prospect.save(update_fields=['sent'])

        attempt_batch_text.delay(
            campaign_prospect.id,
            template_id,
            request.user.id,
            force_skip=force_skip,
        )
        return Response({})

    @swagger_auto_schema(
        responses={'200': UnreadMessagesSerializer()},
        manual_parameters=[unread_parameters],
    )
    @action(detail=False, methods=['get'], pagination_class=None, filter_backends=[])
    def unread(self, request):
        """
        campaign-prospects_unread

        Return the most recent 100 campaign prospects that have an unread message.

        We need to do some non-standard behavior here to limit the amount of messages to something
        managable, but also the count isn't directly that of the queryset count.
        """
        profile = request.user.profile
        is_count_only = request.query_params.get('include_messages') == 'false'

        if profile.is_admin:
            unread_prospect_query = Prospect.objects.filter(
                company=request.user.profile.company,
                has_unread_sms=True,
            )
            unread_campaign_prospect_query = CampaignProspect.objects.filter(
                prospect__in=unread_prospect_query,
            )
            unread_prospect_count = unread_prospect_query.count()
        else:
            accessible_campaign_ids = Campaign.objects.has_access(request.user).filter(
                has_unread_sms=True,
            ).values_list('id', flat=True)
            unread_prospect_query = request.user.profile.unread_prospects
            unread_campaign_prospect_query = CampaignProspect.objects.filter(
                campaign_id__in=accessible_campaign_ids,
                prospect__in=unread_prospect_query,
            ).distinct()
            unread_prospect_count = unread_campaign_prospect_query.values('prospect').count()

        if is_count_only:
            # Do not fetch the messages, however keep the response data with the same structure.
            count_only_response_data = {
                'count': unread_prospect_count,
                'results': [],
            }
            return Response(count_only_response_data)

        # Limit to just 100 prospects to avoid performance issues.
        # We also create an order for limiting the total amount of campaignprospects while
        # making sure we are not including many entries for some prospects and omitting others
        # because we hit the campaignprospect limit before we hit the prospect limit)
        unread_campaign_prospect_query = unread_campaign_prospect_query.filter(
            prospect__in=unread_prospect_query[:100],
        ).annotate(
            campaign_prospect_order=Window(
                expression=RowNumber(),
                partition_by=[F('prospect__pk')],
                order_by=F('prospect__pk').desc(),
            ),
        ).order_by("campaign_prospect_order")

        # this cuts queries by over 10% and query time by about a third
        # further select or prefetch related make performance worse... need to evaluate if
        # fully hydrated serializer is necessary here.... relay for agent_profile and prospect?
        campaign_prospect_list = unread_campaign_prospect_query.prefetch_related(
            'prospect__messages',
        )

        # Limit to just 200 campaign prospects to avoid performance issues.
        # 200 is enough so the 100 prospects are included and some can be on more than 1 campaign
        # while limiting the performance impact
        cp_serializer = CampaignProspectUnreadSerializer(campaign_prospect_list[:200], many=True)
        response_data = {
            'count': unread_prospect_count,
            'results': cp_serializer.data,
        }
        return Response(response_data)

    @swagger_auto_schema(responses={200: BulkActionResponseSerializer})
    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated, AdminPlusModifyPermission],
        serializer_class=CampaignProspectBulkActionSerializer,
    )
    def bulk_action(self, request, pk=None):
        """
        campaign-prospects_bulk_action

        Perform a bulk action on multiple selected campaign prospects.

        Current available actions: dnc, priority, verify, viewed
        """
        serializer = CampaignProspectBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pk_list = serializer.validated_data.get('values')
        action = serializer.validated_data.get('action')
        toggle_action_count = 0
        for cp in CampaignProspect.objects.filter(pk__in=pk_list):
            toggle_method = CampaignProspect.BulkToggleActions.TOGGLE_METHODS.get(action, None)
            if toggle_method:
                method = toggle_method['method']
                value = toggle_method['value']
                if toggle_method['object'] == 'Prospect':
                    getattr(cp.prospect, method)(request.user, value)
                else:
                    getattr(cp, method)(request.user, value)
                toggle_action_count += 1
        return Response({'rows_updated': toggle_action_count})


class ProspectRelayViewSet(ListModelMixin, GenericViewSet):
    """
    Sherpa agents can setup relays with prospects so that they can send/receive sms messages and
    calls with the prospect through their own device, while masking their number as the sherpa
    number.

    list: List all the prospect relays for the user's company.
    """
    serializer_class = ProspectRelaySerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = None

    def get_queryset(self):
        """
        Filter to just the agents in the same company of the authenticated user.
        """
        return ProspectRelay.objects.filter(
            agent_profile__company=self.request.user.profile.company)

    @swagger_auto_schema(
        responses={200: 'Prospect relay has been disconnected.'},
        request_body=no_body,
    )
    @action(detail=True, methods=['post'])
    def disconnect(self, request, pk=None):
        """
        Remove a relay connection from agent to a prospect.
        """
        relay = self.get_object()
        relay.disconnect()
        return Response({})

    @swagger_auto_schema(request_body=ProspectRelayConnectSerializer)
    @action(detail=False, methods=['post'])
    def connect(self, request, pk=None):
        """
        Connect an agent to a prospect.
        """
        serializer = ProspectRelayConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        agent_profile = validated['agent_profile']
        prospect = validated['prospect']

        # Verify that the agent and prospect are in the user's company.
        request_user_company = request.user.profile.company
        if agent_profile.company != request_user_company:
            return Response({'detail': 'Agent not found in company.'}, status=400)
        elif prospect.company != request_user_company:
            return Response({'detail': 'Prospect not found in company.'}, status=400)
        elif prospect.sherpa_phone_number_obj.provider != Provider.TELNYX:
            return Response({'detail': 'Not currently an option for this market.'}, status=400)

        try:
            relay, error = ProspectRelay.connect(agent_profile, prospect)
        except TELNYX_ERRORS_FULL as e:
            return handle_telnyx_view_error(e)

        if error:
            return Response({'detail': error}, status=400)

        response_serializer = self.serializer_class(relay)
        return Response(response_serializer.data)


class ProspectTagViewSet(CompanyAccessMixin, ModelViewSet):
    """
    Return list of Prospect Tags for a company.
    """
    serializer_class = ProspectTagSerializer
    model = ProspectTag
    permission_classes = (IsAuthenticated, AdminPlusModifyPermission, CustomTagModify)

    def get_queryset(self):
        return super().get_queryset().order_by('-is_custom', 'name')

    def create(self, request, *args, **kwargs):
        """
        Create new `ProspectTag` with user's `Company` and set `isCustom` to True.
        """
        request.data['is_custom'] = True
        request.data['company'] = request.user.profile.company.id
        return super().create(request, *args, **kwargs)
