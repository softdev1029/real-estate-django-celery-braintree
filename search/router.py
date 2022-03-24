from rest_framework import routers

from .viewsets import StackerSearchViewSet


router = routers.SimpleRouter()

# Property Stacker Routes
router.register(r'search/stacker', StackerSearchViewSet, basename='stacker-search')
