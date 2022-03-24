from django_object_actions import DjangoObjectActions
from import_export.admin import ExportActionMixin

from django.contrib import admin

from sherpa.models import (
    FeatureNotification,
    InvitationCode,
    UserFeatureNotification,
    UserProfile,
)
from .models import UserLogin
from .resources import UserProfileResource


class UserProfileAdmin(DjangoObjectActions, ExportActionMixin, admin.ModelAdmin):
    def assume_identity(self, request, obj):
        request.user.profile.admin_switch_company(obj.company)

    assume_identity.short_description = "Change your company to this user's company."

    change_actions = ('assume_identity',)
    list_display = ['user', 'phone_display', 'company', 'role', 'disclaimer_signature',
                    'disclaimer_timestamp']
    raw_id_fields = ('company', 'user')
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'company__name']
    resource_class = UserProfileResource
    list_select_related = ('company', 'user')


class InvitationCodeAdmin(admin.ModelAdmin):
    def active_subscriber_count(self, obj):
        return obj.active_subscribers.count()

    def active_user_count(self, obj):
        return obj.active_users.count()

    list_display = [
        'code', 'is_active', 'discount_code', 'active_subscriber_count', 'active_user_count',
    ]


class UserLoginAdmin(admin.ModelAdmin):
    list_display = ['user', 'timestamp', 'ip_address']
    search_fields = ['user__email', 'ip_address']


class UserFeatureNotificationAdmin(admin.ModelAdmin):
    list_display = ['user_profile', 'feature_notification',
                    'display_count', 'is_tried', 'is_dismissed', 'dismissed_or_tried_dt']


admin.site.register(InvitationCode, InvitationCodeAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(UserLogin, UserLoginAdmin)
admin.site.register(FeatureNotification)
admin.site.register(UserFeatureNotification, UserFeatureNotificationAdmin)
