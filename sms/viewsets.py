from drf_yasg.utils import swagger_auto_schema
from twilio.twiml.messaging_response import MessagingResponse

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import IntegrityError
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponse
from rest_framework.decorators import action
from rest_framework.mixins import (
    CreateModelMixin,
    ListModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from core.mixins import CompanyAccessMixin
from sherpa.models import SMSMessage, SMSPrefillText, SMSTemplate
from sherpa.permissions import StaffPlusModifyPermission
from .models import CarrierApprovedTemplate, SMSResult, SMSTemplateCategory
from .serializers import (
    CarrierApprovedTemplateSerializer,
    QuickReplyDetailSerializer,
    QuickReplySerializer,
    SMSMessageSerializer,
    SMSTemplateCategorySerializer,
    SMSTemplateCategorySortSerializer,
    SMSTemplateSerializer,
)
from .tasks import sms_message_received_router, telnyx_status_callback_task


class SMSTemplateViewSet(CompanyAccessMixin, ListModelMixin, UpdateModelMixin, CreateModelMixin,
                         GenericViewSet):
    model = SMSTemplate
    serializer_class = SMSTemplateSerializer
    permission_classes = (StaffPlusModifyPermission,)
    pagination_class = None

    def perform_create(self, serializer):
        """
        Save the request user and company when creating the instance.
        """
        user = self.request.user
        serializer.save(created_by=user, company=user.profile.company)

    def perform_update(self, serializer):
        """
        Update the instance and handle any sorting changes.
        """
        obj = self.get_object()

        old_category = obj.category
        new_category = serializer.validated_data.get('category', old_category)
        category_changed = not old_category or (old_category.pk != new_category.pk)
        old_sort_order = obj.sort_order
        new_sort_order = serializer.validated_data.pop('sort_order', None)
        if category_changed:
            if not new_sort_order or new_sort_order > new_category.max_order:
                new_sort_order = new_category.max_order + 1
        serializer.save()
        obj.refresh_from_db()

        if category_changed:
            # Update all the other templates in the original category to fill in the possible
            # hole left by the moved template.
            new_category.set_order(obj, new_sort_order, from_new=True)
            if old_category:
                old_category.template_moved(old_sort_order)
        else:
            if old_category and new_sort_order and old_sort_order != new_sort_order:
                old_category.set_order(obj, new_sort_order)

    @action(detail=True, methods=['post'])
    def copy_alternate_message(self, request, pk=None):
        """
        Copy this `SMSTemplate`'s 'alternate_message' to the associated `Company`'s
        'default_alternate_message'.
        """
        template = self.get_queryset().first()
        template.copy_alternate_message(request.data['message'])
        return Response(status=200)

    @action(detail=False, methods=['get'])
    def list_valid(self, request, pk=None):
        """
        DEPRECATED: This is not used.

        Override's generic list of templates to provide valid templates only where a valid template
        is one that passes the banned words check. This is separate because templates with banned
        words need to be pulled for editing purposes but do not need to be returned when listing
        available templates when viewing a campaign.
        """
        queryset = SMSTemplate.valid_templates(self.request.user.profile.company)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class SMSMessageViewSet(UpdateModelMixin, GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = SMSMessageSerializer

    def get_queryset(self):
        """
        Filter queryset so that users can only get the messages from their own prospects.
        """
        return SMSMessage.objects.filter(prospect__company=self.request.user.profile.company)

    def perform_update(self, serializer):
        """
        If we're marking a message as read, need to check if the full prospect mark as read needs to
        be processed.
        """
        serializer.save()
        if serializer.validated_data.get('unread_by_recipient') is False:
            prospect = self.get_object().prospect
            if not prospect.messages.filter(unread_by_recipient=True).exists():
                prospect.mark_as_read()

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, permission_classes=[AllowAny], methods=['post'])
    def received_telnyx(self, request):
        """
        Handle the received message webhook from telnyx.
        """
        payload = request.data.get('data').get('payload')
        from_number = payload.get('from').get('phone_number')
        to_number = payload.get('to')
        message = payload.get('text')
        media = payload.get('media')
        media_url = None

        if len(media):
            media_url = media[0].get('url')
        # Routes to a different task if this is a relay from an agent or from a prospect.
        sms_message_received_router.delay(from_number, to_number, message, media_url)
        return Response({})

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, permission_classes=[AllowAny], methods=['post'])
    def received_twilio(self, request):
        """
        Handle the received message webhook from Twilio.
        """
        from_number = request.data.get('_from')
        to_number = request.data.get('_to')
        message = request.data.get('_body')
        media_url = request.data.get('_media_url0')

        sms_message_received_router.delay(from_number, to_number, message, media_url)
        # Send back a TwiML response to prevent 12300 invalid content errors.
        return HttpResponse(MessagingResponse())

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, permission_classes=[AllowAny], methods=['post'])
    def received_phone_broker(self, request):
        """
        Handle the received message from the phone broker.
        """
        from_number = request.data.get('from')
        to_number = request.data.get('to')
        message = request.data.get('text')
        # TODO We need to use this in the future.
        # It could be used to tie the message received to the message sent.
        request.data.get('reference_id')
        media_urls = request.data.get('media_urls')
        if not to_number or not from_number or not message:
            # TODO Create a serializer for this... just want something running for now
            return Response({'detail': 'Missing required fields'}, status_code=400)

        sms_message_received_router.delay(from_number, to_number[0], message, media_urls)
        return Response({})


class QuickReplyViewSet(CompanyAccessMixin, ModelViewSet):
    serializer_class = QuickReplySerializer
    pagination_class = None
    model = SMSPrefillText
    permission_classes = (StaffPlusModifyPermission,)

    def get_serializer_class(self):
        if self.action in ['retrieve', 'update', 'partial_update']:
            return QuickReplyDetailSerializer
        return QuickReplySerializer

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(company=user.profile.company)


class SMSResultViewSet(GenericViewSet):
    """
    Viewset to handle results from our phone provider's callbacks.
    """
    permission_classes = (AllowAny,)
    queryset = SMSResult.objects.all()

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, methods=['post'])
    def telnyx(self, request):
        """
        Status callback for the telnyx webhook.

        Telnyx webhook docs:
        https://developers.telnyx.com/docs/v2/development/api-guide/webhooks
        """
        payload = request.data.get('data').get('payload')
        provider_message_id = payload.get('id')
        status = payload.get('to')[0].get('status')
        error_code = payload.get('errors')[0].get('code') if payload.get('errors') else ''
        telnyx_status_callback_task.delay(provider_message_id, status, error_code)
        return Response({})

    @swagger_auto_schema(method='post', auto_schema=None)
    @action(detail=False, methods=['post'])
    def twilio(self, request):
        """
        Status callback for the twilio webhook.
        """
        provider_message_id = request.data.get('_message_sid')
        status = request.data.get('_message_status')
        error_code = request.data.get('_error_code', '')
        telnyx_status_callback_task.delay(provider_message_id, status, error_code)
        # Send back a TwiML response to prevent 12300 invalid content errors.
        return HttpResponse(MessagingResponse())


class CarrierApprovedTemplateViewSet(ListModelMixin, GenericViewSet):
    """
    Lists all active carrier-approved templates.

    DEPRECATED: Carrier-approved templates will no longer be used.
    """
    serializer_class = CarrierApprovedTemplateSerializer
    pagination_class = None
    model = CarrierApprovedTemplate
    queryset = CarrierApprovedTemplate.objects.filter(is_active=True)


class SMSTemplateCategoriesViewSet(CompanyAccessMixin, ModelViewSet):
    """
    Viewset to handle SMS template categories.
    """
    model = SMSTemplateCategory
    serializer_class = SMSTemplateCategorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        templates = SMSTemplate.objects.filter(id=OuterRef('smstemplate'))
        return qs.annotate(
            templates=ArrayAgg(
                Subquery(templates.values('id')),
                filter=Q(smstemplate__is_active=True),
                ordering='smstemplate__sort_order',
            ),
        )

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            msg = {
                "nonFieldErrors": ["The title must be unique."],
            }
            return Response(msg, status=400)

    def perform_create(self, serializer):
        user = self.request.user
        templates = serializer.validated_data.pop('templates', [])
        category = serializer.save(company=user.profile.company, is_custom=True)
        SMSTemplate.objects.filter(id__in=templates).update(
            category_id=category.id,
        )

    def list(self, request):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def templates(self, request, pk=None):
        """
        Returns a list of all currently active templates belonging to the category.
        """
        category = self.get_object()
        templates = category.smstemplate_set.filter(is_active=True).order_by('sort_order')
        serializer = SMSTemplateSerializer(templates, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], serializer_class=SMSTemplateCategorySortSerializer)
    def sort(self, request, pk=None):
        """
        Sorts the underlying templates in the category by moving an individual template.
        """
        category = self.get_object()
        serializer = SMSTemplateCategorySortSerializer(
            data=request.data,
            context={'category': category, 'company': request.user.profile.company},
        )
        serializer.is_valid(raise_exception=True)

        category.set_order(
            template=SMSTemplate.objects.get(id=serializer.validated_data.get('template')),
            order=serializer.validated_data.get('order'),
        )

        return Response(SMSTemplateSerializer(category.smstemplate_set.all(), many=True).data)
