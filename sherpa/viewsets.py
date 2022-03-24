from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from core.mixins import CompanyAccessMixin
from .models import InvitationCode, SupportLink, ZapierWebhook
from .permissions import AdminPlusModifyPermission
from .serializers import (
    InvitationCodeWithBraintreeSerializer,
    SupportLinkSerializer,
    ZapierWebhookSerializer,
)


class SupportLinkViewSet(ListModelMixin, GenericViewSet):
    serializer_class = SupportLinkSerializer
    queryset = SupportLink.objects.all()


class ZapierWebhookViewSet(CompanyAccessMixin, ModelViewSet):
    serializer_class = ZapierWebhookSerializer
    model = ZapierWebhook
    permission_classes = (IsAuthenticated, AdminPlusModifyPermission)

    def perform_create(self, serializer):
        """
        Always save the new webhook as the user's company.
        """
        company = self.request.user.profile.company
        serializer.save(company=company)


class InvitationCodeViewSet(RetrieveModelMixin, GenericViewSet):
    """
    Full data about an invitation code, including discount data from braintree.
    """
    permission_classes = (IsAuthenticated,)
    queryset = InvitationCode.objects.filter(is_active=True)
    serializer_class = InvitationCodeWithBraintreeSerializer
