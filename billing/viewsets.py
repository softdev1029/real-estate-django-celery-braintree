from rest_framework.mixins import ListModelMixin
from rest_framework.viewsets import GenericViewSet

from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(ListModelMixin, GenericViewSet):
    queryset = Plan.public.all()
    serializer_class = PlanSerializer
    pagination_class = None
