from rest_framework.viewsets import ModelViewSet

from core.mixins import CompanyAccessMixin
from .models import PropertyTag
from .serializers import PropertyTagSerializer


class PropertyTagViewSet(CompanyAccessMixin, ModelViewSet):
    """
    Endpoint to fetch and modify property tags for a company.
    """
    model = PropertyTag
    serializer_class = PropertyTagSerializer
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.profile.company)
