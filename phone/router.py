from rest_framework import routers

from phone.viewsets.brand import BrandViewSet
from phone.viewsets.provider import ProviderViewSet

router = routers.DefaultRouter()
router.register('phone/providers', ProviderViewSet, basename='phoneprovider')
router.register('phone/brands', BrandViewSet, basename='brandrequest')
