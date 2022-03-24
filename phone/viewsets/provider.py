from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from ..models.provider import Provider
from ..serializers.provider import ProviderSerializer


class ProviderViewSet(ReadOnlyModelViewSet):
    """
    Provide endpoints for getting Provider information.
    """
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    permission_classes = (IsAuthenticated,)
