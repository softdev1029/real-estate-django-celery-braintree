from datetime import timedelta

from drf_yasg.utils import swagger_auto_schema
from pypodio2.transport import TransportException

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.parsers import FileUploadParser, FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from billing.exceptions import SubscriptionException
from billing.models import Gateway
from billing.serializers import (
    BraintreeCreditCardSerializer,
    BraintreeSubscriptionSerializer,
    BraintreeTransactionSerializer,
)
from campaigns.serializers import CampaignStatsSerializer
from core.mixins import CompanyAccessMixin
from core.utils import select_keys
from services.crm.podio import podio
from services.crm.podio.utils import fetch_data_to_sync
from sherpa.models import (
    Company,
    InternalDNC,
    InvitationCode,
    LeadStage,
    Prospect,
    SherpaTask,
    SubscriptionCancellationRequest,
    UploadInternalDNC,
)
from sherpa.permissions import AdminPlusModifyPermission, AdminPlusPermission
from sherpa.serializers import EmptySerializer
from sherpa.utils import get_average_rate
from .docs import end_date_param, start_date_param
from .models import (
    CompanyGoal,
    CompanyPodioCrm,
    CompanyPropStackFilterSettings,
    DownloadHistory,
    PodioFieldMapping,
    PodioProspectItem,
    TelephonyConnection,
)
from .serializers import (
    CompanyCampaignStatsSerializer,
    CompanyGoalSerializer,
    CompanyPaymentMethodGetSerializer,
    CompanyPaymentMethodSerializer,
    CompanyPodioIntegrationSerializer,
    CompanyProfileStatsSerializer,
    CompanyPropStackFilterSettingsSerializer,
    CompanyRegisterSerializer,
    CompanySerializer,
    CompanySlowSerializer,
    DNCBulkRemoveSerializer,
    DNCExportSerializer,
    DNCSerializer,
    DownloadHistorySerializer,
    FileDownloadPollingSerializer,
    LeadStageSerializer,
    ProspectCountSerializer,
    PurchaseSherpaCreditsSerializer,
    SetInvitationCodeSerializer,
    SubscriptionCancellationRequestSerializer,
    SubscriptionCancellationResponseSerializer,
    SubscriptionRequestSerializer,
    TelephonyConnectionSerializer,
    TelephonySyncSerializer,
    TemplateListSerializer,
)
from .tasks import (
    bulk_remove_internal_dnc_task,
    generate_download,
    set_freshsuccess_billing,
    upload_internal_dnc_task,
)
from .utils import handle_cancellation_flow, make_podio_webhook_url, verify_dnc_upload_files


class CompanyViewSet(CreateModelMixin, RetrieveModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = CompanySerializer
    permission_classes = (IsAuthenticated, )

    def get_serializer_class(self):
        if self.action == 'create':
            return CompanyRegisterSerializer
        return self.serializer_class

    def get_queryset(self):
        """
        Limit queryset to company of the current user.
        """
        return Company.objects.filter(pk=self.request.user.profile.company.pk)

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = Company.objects.register(user=request.user, **serializer.validated_data)
        return Response({'id': company.pk}, 201)

    @action(detail=True, methods=['post'])
    def retry_subscription(self, request, pk=None):
        """
        Retry the charge for the subscription payment.
        """
        company = self.get_object()
        updated_company = company.check_subscription_retry()

        if updated_company.subscription_status != Company.SubscriptionStatus.ACTIVE:
            return Response({'detail': 'Failed to re-activate company subscription'}, 400)

        serializer = self.serializer_class(updated_company)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def copy_alternate_message(self, request, pk=None):
        """
        Copy `Company`'s 'default_alternate_message' to associated `SMSTemplate`'s
        'alternate_message'.
        """
        company = self.get_object()
        company.copy_alternate_message_to_templates()
        return Response(status=200)

    @action(detail=True, methods=['get'], serializer_class=CompanySlowSerializer)
    def uploads_remaining(self, request, pk=None):
        """
        Uploads remaining for larger accounts takes a while to get and puts a load on db, needs
        be a separate endpoint off of company until this is reworked.
        """
        serializer = CompanySlowSerializer(self.get_object())
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: CompanyCampaignStatsSerializer()})
    @action(detail=True, methods=['get'])
    def campaign_meta_stats(self, request, pk=None):
        """
        Return the meta campaign stats for the entire company - takes all the company's active
        campaigns and aggregates the stats.
        """
        company = self.get_object()
        active_campaigns = company.campaign_set.filter(is_archived=False)

        # Build up the data to pass into the serializer
        active_campaign_count = active_campaigns.count()
        new_lead_count = 0
        total_sms_sent_count = 0
        delivery_rates = []
        response_rates = []

        for campaign in active_campaigns:
            new_lead_count += campaign.campaign_stats.total_leads
            total_sms_sent_count += campaign.total_sms_sent_count
            delivery_rates.append(campaign.delivery_rate)
            response_rates.append(campaign.response_rate_sms)

        campaign_stats_data = {
            'active_campaign_count': active_campaign_count,
            'new_lead_count': new_lead_count,
            'total_sms_sent_count': total_sms_sent_count,
            'delivery_rate': get_average_rate(delivery_rates),
            'response_rate': get_average_rate(response_rates),
        }
        serializer = CompanyCampaignStatsSerializer(data=campaign_stats_data)
        serializer.is_valid()
        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[start_date_param, end_date_param],
        responses={200: CampaignStatsSerializer()},
    )
    @action(detail=True, methods=['get'])
    def campaign_stats(self, request, pk=None):
        """
        companies_campaign_stats

        Return time-filtered stats for each of the company's campaigns.
        """
        start_date = request.query_params.get(
            'start_date',
            timezone.now().date() - timedelta(days=7),
        )
        end_date = request.query_params.get('end_date', timezone.now().date())

        # Build up the aggregated data to pass into serializer.
        data = request.user.profile.company.campaign_meta_stats(start_date, end_date)

        # Aggregate the stats so that we can return a single summary instance for the campaign.
        serializer = CampaignStatsSerializer(data, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        manual_parameters=[start_date_param, end_date_param],
        responses={200: {}},
    )
    @action(detail=False, methods=['get'], pagination_class=None)
    def export_campaign_meta_stats(self, request):
        """
        CSV Export campaign meta stats or profile stats.
        """
        filename = f'campaign-meta-stats-{timezone.now().date()}.csv'
        start_date = request.query_params.get(
            'start_date',
            timezone.now().date() - timedelta(days=7),
        )
        end_date = request.query_params.get('end_date', timezone.now().date())
        filters = {
            'start_date': start_date,
            'end_date': end_date,
            'filename': filename,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=request.user.profile.company,
            download_type=DownloadHistory.DownloadTypes.CAMPAIGN_META_STATS,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)
        return Response({"id": download.uuid})

    @swagger_auto_schema(
        manual_parameters=[start_date_param, end_date_param],
        responses={200: {}},
    )
    @action(detail=False, methods=['get'], pagination_class=None)
    def export_profile_stats(self, request):
        """
        CSV Export profile stats.
        """
        filename = f'profile-stats-{timezone.now().date()}.csv'
        start_date = request.query_params.get(
            'start_date',
            timezone.now().date() - timedelta(days=7),
        )
        end_date = request.query_params.get('end_date', timezone.now().date())
        filters = {
            'start_date': start_date,
            'end_date': end_date,
            'filename': filename,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=request.user.profile.company,
            download_type=DownloadHistory.DownloadTypes.PROFILE_STATS,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        generate_download.delay(download.uuid)
        return Response({"id": download.uuid})

    @swagger_auto_schema(
        responses={200: None},
        request_body=PurchaseSherpaCreditsSerializer,
    )
    @action(detail=True, methods=['post'])
    def purchase_credits(self, request, pk=None):
        """
        Purchase Sherpa Credits.

        request must include `amount` which must be greater than value in `settings.MIN_CREDIT`
        """
        amount = request.data.get('amount', 0)
        if not amount:
            return Response({'detail': 'Must include amount.'}, status=400)

        error = self.get_object().credit_sherpa_balance(amount)
        if error:
            return Response({'detail': error}, status=400)

        return Response(status=200)

    @swagger_auto_schema(manual_parameters=[start_date_param, end_date_param])
    @action(detail=True, methods=['get'], serializer_class=CompanyProfileStatsSerializer)
    def profile_stats(self, request, pk=None):
        """
        Return the stats for the company's agents.
        """
        company = self.get_object()
        start_date = parse_date(request.query_params.get('start_date', ''))
        end_date = parse_date(request.query_params.get('end_date', ''))
        stats = company.user_profile_stats(start_date, end_date)
        serializer = CompanyProfileStatsSerializer(stats, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: BraintreeTransactionSerializer(many=True)})
    @action(detail=True, methods=['get'], permission_classes=[AdminPlusPermission])
    def transactions(self, request, pk=None):
        """
        Return the companies transactions from the braintree source.
        """
        company = self.get_object()
        transactions = company.braintree_transactions
        serializer = BraintreeTransactionSerializer(transactions, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(method='get', responses={200: BraintreeSubscriptionSerializer()})
    @swagger_auto_schema(
        method='post',
        request_body=SubscriptionRequestSerializer,
        responses={200: BraintreeSubscriptionSerializer()},
    )
    @action(detail=True, methods=['get', 'post'], permission_classes=[AdminPlusPermission])
    def subscription(self, request, pk=None):
        """
        get: Get the company's subscription data.
        post: Create a new subscription for the company.
        """
        if request.method == 'POST':
            company = self.get_object()
            post_serializer = SubscriptionRequestSerializer(data=request.data)
            post_serializer.is_valid(raise_exception=True)
            try:
                subscription_response = company.create_subscription(
                    post_serializer.data.get('plan_id'),
                    post_serializer.data.get('annual'),
                )
            except SubscriptionException as e:
                return Response({'detail': str(e)}, status=400)

            if subscription_response.is_success:
                subscription = subscription_response.subscription
                setattr(subscription, "is_cancellable", company.is_cancellable)
                setattr(subscription, "is_annual", company.has_annual_subscription)
                serializer = BraintreeSubscriptionSerializer(subscription)
            else:
                return Response({
                    'detail': f'Error creating subscription `{subscription_response.message}`',
                })
        else:
            company = self.get_object()
            subscription = company.subscription

            if subscription:
                setattr(subscription, "is_cancellable", company.is_cancellable)
                setattr(subscription, "is_annual", company.has_annual_subscription)

            serializer = BraintreeSubscriptionSerializer(subscription)

        return Response(serializer.data)

    @swagger_auto_schema(
        method='get',
        serializer_class=CompanyPaymentMethodGetSerializer,
        responses={200: BraintreeCreditCardSerializer},
    )
    @swagger_auto_schema(method='put', responses={200: BraintreeCreditCardSerializer})
    @swagger_auto_schema(method='post', responses={201: BraintreeCreditCardSerializer})
    @action(
        detail=True,
        methods=['get', 'put', 'post'],
        permission_classes=[AdminPlusPermission],
        serializer_class=CompanyPaymentMethodSerializer,
    )
    def payment_methods(self, request, pk=None):
        """
        companies-payment_methods

        get: Return the customer's primary payment method data
        post: Create a new payment method.
        put: Update an existing payment method and retry payment if past due.
        """
        company = self.get_object()

        if request.method == 'GET':
            request_serializer = CompanyPaymentMethodGetSerializer(data=request.data)
        elif request.method in ['POST', 'PUT']:
            request_serializer = CompanyPaymentMethodSerializer(data=request.data)

        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data
        user = request.user
        customer = company.customer

        if request.method == 'GET':
            # Return the company's payment method. Need to return early because this is not a
            # `SuccessResult` response, unlike create/update.

            if not customer:
                # Billing exempt companies might not have customer.
                return Response()

            token = customer.payment_methods[0].token
            result = Gateway.payment_method.find(token)
            serializer = BraintreeCreditCardSerializer(result)
            return Response(serializer.data)

        if not customer:
            # Create a new customer which creates a payment method.
            result = Gateway.customer.create({
                'first_name': user.profile.user.first_name,
                'last_name': user.profile.user.last_name,
                'payment_method_nonce': data['payment_method_nonce'],
                'company': company.name,
                'phone': user.profile.phone,
                'email': user.profile.user.email,
            })
            serializer = EmptySerializer()
            company.braintree_id = result.customer.id
            company.save()

            # Update the freshsuccess account.
            set_freshsuccess_billing.delay(company.id)

            return Response(serializer.data, status=201)

        is_create = request.method == 'POST'
        if is_create:
            # Create a payment method.  Should this delete existing payment methods?
            result = Gateway.payment_method.create({
                'customer_id': company.braintree_id,
                'payment_method_nonce': data['payment_method_nonce'],
            })
        else:
            # Update a payment method.
            token = customer.payment_methods[0].token
            result = Gateway.payment_method.update(token, {
                'payment_method_nonce': data['payment_method_nonce'],
                'options': {'make_default': True},
            })
            company.check_subscription_retry()

        if result.is_success:
            serializer = BraintreeCreditCardSerializer(result.payment_method)
            status_code = 201 if is_create else 200
            return Response(serializer.data, status=status_code)

        error_verb = 'create' if is_create else 'update'
        return Response({'detail': f'We were unable to {error_verb} your payment method.'}, 400)

    @swagger_auto_schema(
        responses={200: CompanySerializer()},
        request_body=SetInvitationCodeSerializer(),
    )
    @action(detail=True, methods=['post'])
    def invitation_code(self, request, pk=None):
        """
        Set the invitation code for a company.
        """
        company = self.get_object()
        request_serializer = SetInvitationCodeSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        try:
            code = request_serializer.data.get('code')
            invitation_code = InvitationCode.objects.get(code=code)
        except InvitationCode.DoesNotExist:
            return Response({'detail': 'Invitation code does not exist.'}, status=400)

        company.invitation_code = invitation_code
        company.save(update_fields=['invitation_code'])
        response_serializer = self.serializer_class(company)
        return Response(response_serializer.data)

    @swagger_auto_schema(
        responses={200: ProspectCountSerializer()},
    )
    @action(detail=True, methods=['get'])
    def prospect_count(self, request, pk=None):
        """
        Returns the total count of prospects the company has.
        """
        company = self.get_object()
        count = company.prospect_set.count()
        serializer = ProspectCountSerializer(data={'count': count})
        serializer.is_valid()
        return Response(serializer.data)

    @swagger_auto_schema(method='get', responses={200: TemplateListSerializer()})
    @swagger_auto_schema(
        method='post',
        request_body=TemplateListSerializer,
        responses={201: TemplateListSerializer()},
    )
    @action(
        detail=True,
        methods=['get', 'post'],
        permission_classes=[AdminPlusPermission],
        serializer_class=TemplateListSerializer,
    )
    def templates(self, request, pk=None):
        """
        Manages a company's carrier-approved templates.

        get: List which carrier-approved templates a company currently has chosen.
        post: Choose which carrier-approved templates a company will use. Minimum of 30 required.
        """
        company = self.get_object()
        if request.method == 'POST':
            serializer = TemplateListSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            add = set(serializer.validated_data.get('templates', []))
            company.carrier_templates.add(*add)

            current = set(company.carrier_templates.values_list('pk', flat=True))
            remove = current ^ add
            company.carrier_templates.remove(*remove)
            status = 201
        else:
            data = {
                'templates': company.carrier_templates.values_list('pk', flat=True),
            }
            serializer = TemplateListSerializer(data)
            status = 200

        return Response(serializer.data, status)

    @action(detail=True, methods=['get'])
    def integrations(self, request, pk=None):
        """
        Returns a dict with the integration that is active or not.

        Example: { 'podio': True }
        Signifies that user has integrated with podio
        """
        company = self.get_object()
        crm_integration = company.companypodiocrm_set.first()
        crm_status = crm_integration is not None
        try:
            podio_integration = CompanyPodioCrm.objects.get(company=company)
            if not podio_integration.organization and \
               podio_integration.workspace and \
               podio_integration.application is not None:
                crm_status = False
        except CompanyPodioCrm.DoesNotExist:
            pass

        return Response(
            {'podio': crm_status},
            status=200,
        )

    @action(detail=True, methods=["get"])
    def get_podio_integration(self, request, pk=None):
        """Returns integration data"""
        company = self.get_object()
        crm_integration = get_object_or_404(CompanyPodioCrm, company=company)
        serializer = CompanyPodioIntegrationSerializer(crm_integration)

        return Response(serializer.data)


class CompanyGoalViewSet(CompanyAccessMixin, ModelViewSet):
    serializer_class = CompanyGoalSerializer
    permission_classes = (IsAuthenticated,)
    model = CompanyGoal

    @action(detail=False, methods=['get'])
    def current(self, request, pk=None):
        """
        Get current company goal.
        """
        now = timezone.now()
        goal = self.get_queryset().get(
            start_date__lte=now,
            end_date__gte=now,
        )
        serializer = self.get_serializer(goal, many=False)
        return Response(serializer.data)


class LeadStageViewSet(CompanyAccessMixin, ModelViewSet):
    serializer_class = LeadStageSerializer
    model = LeadStage
    permission_classes = (IsAuthenticated, AdminPlusModifyPermission)

    def create(self, request, *args, **kwargs):
        """
        Need to set the company before sending to create as it's needed for validation.
        """
        request.data['company'] = request.user.profile.company.id
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """
        Need to set the company before sending to update as it's needed for validation.
        """
        request.data['company'] = request.user.profile.company.id
        return super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(is_custom=True)


class DownloadHistoryViewSet(CompanyAccessMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet):  # noqa: E501
    serializer_class = DownloadHistorySerializer
    model = DownloadHistory
    permission_classes = (IsAuthenticated,)
    lookup_field = 'uuid'

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(is_hidden=False)

    @action(detail=True, methods=['get'])
    def poll(self, request, uuid=None):
        """
        An endoint to use when a file download has been requested but not yet completed.
        Used to get the status and file url (when ready).
        """
        download = self.get_object()
        serializer = FileDownloadPollingSerializer(download)
        return Response(serializer.data)


class DNCViewSet(CompanyAccessMixin, GenericViewSet):
    """
    DNC viewset that only has actions to upload, export, and poll data.
    """
    serializer_class = DNCSerializer
    permission_classes = (IsAuthenticated, AdminPlusPermission)
    model = InternalDNC

    @action(
        detail=False,
        methods=['post'],
        parser_classes=[FormParser, MultiPartParser, FileUploadParser],
    )
    def upload(self, request):
        """
        Handles upload of `one-column` (Phone) CSV file with phone numbers to add to DNC List.
        """
        user = request.user
        company = user.profile.company
        upload_id = []

        results = verify_dnc_upload_files(request)

        for file in results["files"]:
            upload = UploadInternalDNC.objects.create(
                company=company,
                created_by=user,
                file=file["file"],
                uploaded_filename=str(file["file"]),
                has_column_header=file["has_header"],
            )
            upload_internal_dnc_task.delay(upload.id)
            upload_id.append(upload.id)

        data = {
            'id': upload_id,
            'has_error': results["has_error"],
            'detail': results["error_message"],
        }
        return Response(data)

    @swagger_auto_schema(responses={200: DNCBulkRemoveSerializer()})
    @action(
        detail=False,
        methods=['post'],
        parser_classes=[FormParser, MultiPartParser, FileUploadParser],
    )
    def bulk_remove(self, request):
        """
        Handles upload of a one column csv file with phone numbers to remove from DNC list.
        """
        user = request.user
        results = verify_dnc_upload_files(request)

        if not results["has_error"]:
            for file in results["files"]:
                bulk_remove_internal_dnc_task(file["file"], user)

        serializer = DNCBulkRemoveSerializer({
            'has_error': results["has_error"],
            'detail': results["error_message"],
        })
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def poll(self, request, pk=None):
        """
        Polls the DNC upload to get percent complete.
        """
        upload = UploadInternalDNC.objects.get(pk=pk)
        return Response({'percentage': upload.percentage, 'status': upload.status})

    @swagger_auto_schema(responses={200: DNCExportSerializer})
    @action(detail=False, methods=['get'], pagination_class=None)
    def export(self, request):
        """
        Exports the DNC numbers from both InternalDNC and Prospect models.  Provided `uuid` can
        be used to poll for readiness. Clears out DNC list, if has 'clear_dnc' in params.
        """
        company = request.user.profile.company
        filename = f'{company.name}_dnc_{timezone.now().date()}.csv'
        clear_dnc = request.query_params.get('clear_dnc') == 'true'

        filters = {
            'filename': filename,
        }

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=company,
            download_type=DownloadHistory.DownloadTypes.DNC,
            filters=filters,
            status=DownloadHistory.Status.SENT_TO_TASK,
        )

        message = ''
        if clear_dnc:
            removed, updated = company.dnc_list_count
            message = f"You are moving {removed} prospects from your DNC list, " \
                      f"and {updated} prospects are being removed from DNC."

            generate_download.delay(download.uuid, 'clear_dnc_list')
        else:
            generate_download.delay(download.uuid)

        serializer = DNCExportSerializer({'id': download.uuid, 'message': message})
        return Response(serializer.data)


class SubscriptionCancellationRequestViewSet(CompanyAccessMixin, CreateModelMixin, GenericViewSet):
    """
    Endpoint for the cancellation work flow.
    """
    serializer_class = SubscriptionCancellationRequestSerializer
    permission_classes = (IsAuthenticated, AdminPlusPermission)
    model = SubscriptionCancellationRequest

    def perform_create(self, serializer):
        company = self.request.user.profile.company
        return serializer.save(
            company=company,
            requested_by=self.request.user,
        )

    @swagger_auto_schema(responses={201: SubscriptionCancellationResponseSerializer()})
    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cancellation_request = self.perform_create(serializer)

        try:
            data = handle_cancellation_flow(cancellation_request)
            serializer_response = SubscriptionCancellationResponseSerializer(data)
            return Response(serializer_response.data, status=201)
        except Exception as e:
            cancellation_request.delete()
            return Response({'error': str(e)}, status=400)


class TelephonyConnectionViewSet(
    CompanyAccessMixin,
    CreateModelMixin,
    UpdateModelMixin,
    GenericViewSet,
):
    """
    Endpoint to update Telephony connection settings. Requires admin+.
    """
    serializer_class = TelephonyConnectionSerializer
    permission_classes = (AdminPlusPermission,)
    model = TelephonyConnection

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.profile.company)

    def perform_update(self, serializer):
        serializer.save(company=self.request.user.profile.company)

    @swagger_auto_schema(
        responses={200: None},
        request_body=TelephonySyncSerializer,
    )
    @action(detail=False, methods=['post'])
    def sync(self, request, pk=None):
        """
        Sync numbers from this Telephony Connection.
        """
        company_id = request.data.get('id')
        provider = request.data.get('provider')

        if not company_id or not provider:
            return Response({'detail': 'Must include `id` and `provider` in request.'}, 400)
        try:
            instance = TelephonyConnection.objects.get(company__id=company_id, provider=provider)
            instance.sync()
        except Exception as e:
            return Response({'detail': str(e)}, status=500)
        return Response({})


class PodioInterfaceViewSet(GenericViewSet):
    """
    Base viewset that provides the code to initialize the podio client
    """
    permission_classes = (IsAuthenticated,)

    def _init_podio_client(self, company=None):
        company = company or self.request.user.profile.company
        crm_integration = company.companypodiocrm_set.first()
        crm_integration_id = crm_integration.id if crm_integration else 0
        self.company_podio = get_object_or_404(CompanyPodioCrm, id=crm_integration_id)

        tokens = {
            "access": self.company_podio.access_token,
            "refresh": self.company_podio.refresh_token,
            "expires_in": self.company_podio.expires_in_token,
        }
        self.podio_client = podio.PodioClient(
            company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
            tokens,
        )
        self.podio_client.authenticate()


class CompanyPodioIntegrationViewSet(PodioInterfaceViewSet,
                                     CreateModelMixin,
                                     UpdateModelMixin,
                                     GenericViewSet):
    """
    Authentication viewset to store Podio auth information
    """
    serializer_class = CompanyPodioIntegrationSerializer
    model = CompanyPodioCrm
    queryset = CompanyPodioCrm.objects.none()

    def create(self, request):
        """
        Creates a CompanyPodioCrm when a successful authenticate
        happens. creation happens inside the podio-client
        """
        data = request.data
        company = request.user.profile.company
        podio_client = podio.PodioClient(
            company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
        )
        success, error_message = podio_client.authenticate(**data)

        if not success:
            return Response({"error": error_message}, status=400)

        crm_podio_record = CompanyPodioCrm.objects.get(company=company)
        return Response({"integration_id": crm_podio_record.id}, status=201)

    @action(detail=False, methods=["get"])
    def get_crm_integration(self, request, pk=None):
        """
        Provides the integration object, used during an `edit` to users
        integration.
        """
        company = request.user.profile.company
        crm_integration = get_object_or_404(CompanyPodioCrm, company=company)
        serializer = self.get_serializer(crm_integration)
        data = serializer.data.copy()
        data.update({'pk': crm_integration.pk})

        return Response(data)

    def partial_update(self, request, pk=None):
        crm_integration = get_object_or_404(CompanyPodioCrm, pk=pk)
        serializer = self.get_serializer(crm_integration, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({}, status=200)

    @action(detail=False, methods=["get"])
    def get_podio_field_mappings(self, request):
        """
        Provide the field mappings, used during an `edit` to user
        integration
        """
        company = request.user.profile.company
        field_mappings = get_object_or_404(PodioFieldMapping, company=company)

        return Response(field_mappings.fields)

    @action(detail=False, methods=["post"])
    def delete(self, request, pk=None):
        """Delete user podio integration"""
        company = request.user.profile.company
        record = get_object_or_404(CompanyPodioCrm, company=company)
        try:
            # mappings = get_object_or_404(PodioFieldMapping, company=company)
            mappings = PodioFieldMapping.objects.get(company=company)
            mappings.delete()
        except PodioFieldMapping.DoesNotExist:
            pass
        record.delete()
        return Response(status=204)

    def _delete_hooks(self, hook_ids):
        for hook_id in hook_ids:
            self.podio_client.api.Webhook.delete(hook_id)

    def _create_hooks(self, hook_ids):
        """
        Creates webhook for item.update and item.create
        """
        hook_types = ['item.update', 'item.create']
        application = self.company_podio.application
        company = self.request.user.profile.company

        for hook_type in hook_types:
            attributes = {
                'url': make_podio_webhook_url(company.pk),
                'type': hook_type,
            }
            response = self.podio_client.api.Webhook.create("app", application, attributes)\
                                                    .get("response")
            hook_ids.append(response.get("hook_id"))

        return hook_ids

    @action(detail=False, methods=["post"])
    def create_webhook(self, request):
        """Create webhooks for items to listen to changes on CREATE | UPDATE"""
        self._init_podio_client()
        response = {}
        status = 200
        hook_ids = []

        try:
            hook_ids = self._create_hooks(hook_ids)
        except TransportException:
            # if we were not able to create one of the hooks then
            # delete any that may have gone through successfuly
            self._delete_hooks(hook_ids)
            status = 400

        return Response(response, status=status)


class CompanyPodioWorkspaceViewSet(PodioInterfaceViewSet):
    """Views to fetch organization related information from podio"""
    swagger_schema = None

    def _get_workspaces(self, spaces):
        """helper to select partial information from a workspace"""
        return [select_keys(space, ["space_id", "name"]) for space in spaces]

    def _get_orgs(self):
        """Helper to fetch the orgs and transform data provided"""
        organizations = self.podio_client.api.Organization.get_all().get("response")
        orgs = []

        for org in organizations["data"]:
            org_ = select_keys(org, ["org_id", "name", "spaces"])
            org_["spaces"] = self._get_workspaces(org_["spaces"])
            orgs.append(org_)

        return orgs

    @action(detail=False, methods=["get"])
    def get_organizations(self, request):
        """Fetch organizations from user's podio account and workspaces"""
        self._init_podio_client()
        response = None
        status = 200
        try:
            response = self._get_orgs()
        except TransportException as e:
            status = e.status['status']
            response = e.content.get("error", "")

        return Response(response, status=status)


class CompanyPodioApplicationViewSet(PodioInterfaceViewSet):
    """Viewsets to fetch podio application data"""
    swagger_schema = None

    def _get_applications(self, workspace_id):
        """
        Helper function to fetch applications from a workspace

        :param workspace_id Int: The workspace-id user selected
        """
        applications = self.podio_client.api.Workspace.get_applications(workspace_id)\
                                                      .get("response")
        apps = []

        for application in applications["data"]:
            app = {
                "app_id": application.get("app_id"),
                "name": application.get("config", {}).get("name"),
            }
            apps.append(app)
        return apps

    @action(detail=True, methods=['get'])
    def get_all(self, request, pk=None):
        """Returns podio applications from a users podio account"""
        self._init_podio_client()
        response = None
        status = 200
        try:
            response = self._get_applications(pk)
        except TransportException as e:
            status = e.status['status']
            response = e.content.get("error", "")

        return Response(response, status=status)

    def _get_views(self, pk):
        """
        Helper that fetches views from an application

        :param pk Int: Application id
        """
        response = self.podio_client.api.View.get_views(pk)
        views = []

        for view in response.get("response", {}).get("data"):
            view_ = select_keys(view, ["view_id", "name"])
            views.append(view_)

        return views

    @action(detail=True, methods=["get"])
    def get_views(self, request, pk=None):
        """Returns all podio application views"""
        self._init_podio_client()
        response = None
        status = 200
        try:
            response = self._get_views(pk)
        except TransportException as e:
            status = e.status['status']
            response = e.content.get("error", "")

        return Response(response, status=status)

    def _export_items(self, pk, view_id):
        """Exporting podio items from a view"""
        response = self.podio_client.api.Application.export_items_xlsx(pk, view_id)
        items_blob = response.get("response").get("data")
        return items_blob


class CompanyPodioItemsViewSet(PodioInterfaceViewSet):
    """Viewsets to sync to podio"""
    swagger_schema = None

    def create_or_update_podio_item(self, request, pk):
        """
        Helper to create SherpaTask to sync prospect to podio
        """
        task = SherpaTask.objects.filter(
            status=SherpaTask.Status.OPEN,
            attributes__action=request.data.get("action"),
            attributes__prospect_id=str(pk),
        )
        data = {'prospect_id': pk, 'user_id': request.user.pk}
        data.update(request.data)

        # set user qualified lead optimistically
        prospect = Prospect.objects.get(pk=pk)
        updated_instance, activities = prospect.toggle_qualified_lead(request.user, True)
        updated_instance.activities = activities
        updated_instance.save()

        if not task.exists():
            return SherpaTask.objects.create(
                task=SherpaTask.Task.PUSH_TO_PODIO_CRM,
                company=request.user.profile.company,
                created_by=request.user,
                attributes=data,
                delay=60,
            )
        return task.first()

    @action(detail=True, methods=['post'])
    def get_crm_status(self, request, pk=None):
        """Endpoint to check if a prospect is synced to podio"""
        get_object_or_404(PodioProspectItem, prospect=pk)
        return Response({}, status=201)

    @action(detail=True, methods=['post'])
    def sync_to_podio(self, request, pk=None):
        """Sets up a SherpaTask to push a user to podio"""
        task = self.create_or_update_podio_item(request, pk)
        return Response({'task_id': task.pk}, status=201)

    @action(detail=False, methods=["post"])
    def test_create_item(self, request):
        """
        Endpoint to test the creation of an item to podio during the
        integration process.
        """
        self._init_podio_client()
        company = request.user.profile.company
        prospects = Prospect.objects.filter(company=company)
        prospects.query.clear_ordering(True)  # We want any prospect, ordering just slows the query
        mappings = PodioFieldMapping.objects.get(company=company)
        response = None
        status = 200

        try:
            extractedData = fetch_data_to_sync(
                mappings,
                {'prospect_id': prospects[0].pk},
                settings.PODIO_EXAMPLE_PROSPECT)
            response = self.podio_client.api.Item.create(
                self.company_podio.application,
                extractedData,
            )
        except TransportException as e:
            status = e.status['status']
            response = e.content.get("error", "")

        return Response(response, status=status)


class CompanyPodioFieldsViewSet(PodioInterfaceViewSet):
    """Viewset that handles the fetching of podio fields from an app and sherpa fields"""
    swagger_schema = None

    def _get_fields(self, pk):
        """Get =VISIBLE= fields from the podio application"""
        app = self.podio_client.api.Application.get(pk).get('response')
        app_fields = app.get("data", {}).get("fields")
        podio_field_black_list = ["app", "calculation", "image", "contact", "progress", "embed"]

        # only show visible fields AND filter out fields of type APP
        visible_fields = [
            field for field in app_fields
            if field["config"]["visible"] and field["type"] not in podio_field_black_list
        ]
        fields = []

        # collect all data for each field
        for app_field in visible_fields:
            field = select_keys(app_field, ["label", "field_id", "type", "config"])
            field.update(select_keys(app_field, ["visible", "required", "default_value"]))
            fields.append(field)

        return fields

    @action(detail=True, methods=["get"])
    def get_fields(self, request, pk=None):
        """Get the fields from the user's podio application"""
        self._init_podio_client()
        response = None
        status = 200
        try:
            response = self._get_fields(pk)
        except TransportException as e:
            status = e.status["status"]
            response = e.content.get("error", "")

        return Response(response, status=status)

    @action(detail=False, methods=["get"])
    def get_sherpa_fields(self, request):
        """Retrieve the sherpa fields we allow to export"""
        sherpa_fields = {"fields": settings.SHERPA_FIELDS_MAPPING}
        return Response(sherpa_fields, status=200)

    @action(detail=False, methods=["post"])
    def mapped_fields(self, request):
        """Create the fields mapping and save the org/workspace/app ids to our podio integration"""
        self._init_podio_client()
        data = request.data
        status = 200
        response = data
        company = request.user.profile.company

        mapped, created = PodioFieldMapping.objects.get_or_create(
            company=company,
        )
        mapped.fields = data['mapped_sherpa_fields']
        mapped.save()

        podio_integration = CompanyPodioCrm.objects.get(company=company)
        podio_integration.organization = data['podio_metadata']['organization']['value']
        podio_integration.workspace = data['podio_metadata']['workspace']['value']
        podio_integration.application = data['podio_metadata']['application']['value']
        podio_integration.save()
        return Response(response, status=status)


class CompanyPodioWebhooksViewSet(PodioInterfaceViewSet):
    """viewset for podio webhooks endpoints, not finished implemented"""
    swagger_schema = None
    permission_classes = []

    def _validate_hook(self):
        """Validate the webhook to make it active"""
        hook_id = self.request.POST.get("hook_id")
        code = self.request.POST.get("code")
        self.podio_client.api.Webhook.validate(hook_id, code)

        return Response({}, status=200)

    def _get_item(self, request):
        """Helper to fetch the item that was just notified as created/updated"""
        item_id = request.data.get('item_id', 0)
        data = self.podio_client.api.Item.get(int(item_id))
        return data.get('response', {}).get('data', {})

    def _create_item(self, request):
        # TODO: needs implementation
        # - get the item_id from the request
        # - fetch the item just recently changed
        # - create the item on our db
        # item = self._get_item(request)
        # create the data
        pass

    def _update_item(self, request):
        # TODO: needs implementation
        # - get the item_id from the request
        # - fetch the item just recently changed
        # - update the item on our db
        # item = self._get_item(request)
        # get the item in our db to update it's data
        # merge the data
        pass

    @action(detail=True, methods=["post"])
    def items_webhook(self, request, pk=None):
        """
        Endpoint that acts as a dispatch function to the appropriate handlers
        Note: hook.verify needs to be included to verify the webhook to make it active
        """
        company = get_object_or_404(Company, pk=pk)
        self._init_podio_client(company)
        hook_type = request.POST.get("type")

        if hook_type == "hook.verify":
            return self._validate_hook()
        elif hook_type == "item.create":
            self._create_item_hook(request)
        elif hook_type == "item.update":
            self._update_item(request)

        return Response({}, status=200)


class CompanyPropStackFilterSettingsViewSet(CompanyAccessMixin, ModelViewSet):
    """
    Viewsets to save, list and update the property stacker filter settings.
    """
    model = CompanyPropStackFilterSettings
    serializer_class = CompanyPropStackFilterSettingsSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = None
