from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from sherpa.models import PhoneNumber
from sherpa.permissions import AdminPlusModifyPermission
from sherpa.serializers import IntegerListSerializer
from ..serializers import PhoneNumberSerializer


class PhoneNumberViewSet(ListModelMixin, UpdateModelMixin, GenericViewSet):
    """
    list: Fetch the phone number objects that belong to the user's company.
    """
    serializer_class = PhoneNumberSerializer
    permission_classes = (IsAuthenticated,)
    pagination_class = None

    def get_queryset(self):
        """
        Limit to the correct company, based on the market.
        """
        return PhoneNumber.objects.filter(market__company=self.request.user.profile.company)

    @action(detail=True, methods=['post'], permission_classes=[AdminPlusModifyPermission])
    def release(self, request, pk=None):
        """
        Release a phone number from the company and also from Sherpa.
        """
        phone_number = self.get_object()
        phone_number.release()
        return Response({})

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[AdminPlusModifyPermission],
    )
    def bulk_deactivate(self, request, pk=None):
        serializer = IntegerListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_count = PhoneNumber.objects.filter(
            pk__in=serializer.validated_data.get('values'),
        ).update(status=PhoneNumber.Status.INACTIVE)
        return Response({'rows_updated': update_count})

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[AdminPlusModifyPermission],
    )
    def bulk_release(self, request, pk=None):
        serializer = IntegerListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pk_list = serializer.validated_data.get('values')
        released_count = 0
        for number in PhoneNumber.objects.filter(pk__in=pk_list):
            number.release()
            released_count += 1

        return Response({'rows_updated': released_count})
