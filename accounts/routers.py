from rest_framework import routers

from .viewsets import SherpaUserViewSet


router = routers.DefaultRouter()
router.register('users', SherpaUserViewSet)
