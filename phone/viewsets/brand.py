from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from sherpa.permissions import AdminPlusModifyPermission
from phone.serializers.brand import (
    BrandSerializer,
    BrandTransferSerializer
)


class BrandViewSet(ModelViewSet):

    queryset = None  # BrandRequest.objects.all()
    serializer_class = BrandSerializer
    permission_classes = (IsAuthenticated,)

    @action(
        detail=True,
        methods=['post'],
        permission_classes=[AdminPlusModifyPermission],
    )
    def purchase(self, request, pk=None):
        return Response({'status': 'success'}, 200)

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[AdminPlusModifyPermission],
    )
    def transfer(self, request, pk=None):
        serializer = BrandTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response({'status': 'success'}, 200)
