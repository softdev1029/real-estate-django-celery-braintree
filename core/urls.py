from core.settings.base import TEST_MODE
from drf_yasg import openapi
from drf_yasg.views import get_schema_view

from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic.base import RedirectView
from rest_framework.permissions import IsAdminUser

from accounts.routers import router as account_router
from accounts.views import CustomTokenObtainPairView
from billing.views import subscription_webhook
from sherpa import views
from .routers import router


schema_view = get_schema_view(
   openapi.Info(
      title="LeadSherpa API",
      default_version='v1',
   ),
   public=False,
   permission_classes=(IsAdminUser,) if settings.REQUIRE_DOCS_ADMIN else None,
)

api_prefix = 'api/v1/'

urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^$', RedirectView.as_view(url='/admin/')),
    url(r'^status/$', views.status, name='status'),

    # API urls
    path(f'{api_prefix}', include(router.urls)),
    path(f'{api_prefix}auth/', include(account_router.urls)),
    path(
        f'{api_prefix}auth/jwt/create/',
        CustomTokenObtainPairView.as_view(),
        name='jwt-create-override',
    ),
    path(f'{api_prefix}auth/', include('djoser.urls.jwt')),
    url(r'^docs/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # Webhooks
    url(r'^webhook/subscription/$', subscription_webhook, name='webhook_subscription'),

    # Ligitator Check URLS
    url(r'^litigator/check/home/$', views.litigator_check_home, name='litigator_check_home'),
    url(r'^litigator/check/select/$', views.litigator_check_select_file, name='litigator_check_select_file'),
    url(r'^litigator/check/map/$', views.litigator_check_map_fields, name='litigator_check_map_fields'),
    url(r'^litigator/check/start/(?P<check_litigator_hash>[^/]+)/$', views.litigator_check_start, name='litigator_check_start'),
    url(r'^litigator/check/started/confirmation/(?P<check_litigator_hash>[^/]+)/$', views.check_litigator_started_confirmation,name='check_litigator_started_confirmation'),
    url(r'^litigator/check/status/(?P<check_litigator_hash>[^/]+)/$', views.check_litigator_status, name='check_litigator_status'),
    url(r'^litigator/check/export/(?P<check_litigator_hash>[^/]+)/$', views.check_litigator_export, name='check_litigator_export'),
]

if (settings.DEBUG or settings.TEST_MODE) and 'silk' in settings.INSTALLED_APPS:
    urlpatterns += [url(r'^silk/', include('silk.urls', namespace='silk')),]
