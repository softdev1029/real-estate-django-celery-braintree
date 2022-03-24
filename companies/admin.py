from django_object_actions import DjangoObjectActions
from import_export.admin import ExportActionMixin

from django.contrib import admin

from companies.tasks import modify_freshsuccess_account
from sherpa.models import (
    Company,
    InternalDNC,
    LeadStage,
    RoiStat,
    SMSPrefillText,
    SubscriptionCancellationRequest,
    UpdateMonthlyUploadLimit,
    UploadInternalDNC,
    ZapierWebhook,
)
from .models import (
    CompanyChurn,
    CompanyGoal,
    CompanyPodioCrm,
    CompanyPropStackFilterSettings,
    CompanyUploadHistory,
    DownloadHistory,
    PodioFieldMapping,
    TelephonyConnection,
)
from .resources import CompanyResource


class AnnualUsersFilter(admin.SimpleListFilter):
    """
    This class is used for filtering annual subscription users
    in django admin panel for company model.
    """

    title = "annual users"
    parameter_name = "has_annual_subscription"

    def lookups(self, request, model_admin):
        return (
            ("true", True),
            ("false", False),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if not self.value():
            return queryset
        if self.value().lower() == "true":
            company_ids = [
                company_obj.id
                for company_obj in queryset
                if company_obj.has_annual_subscription
            ]
            return queryset.filter(id__in=company_ids)
        elif self.value().lower() == "false":
            company_ids = [
                company_obj.id
                for company_obj in queryset
                if not company_obj.has_annual_subscription
            ]
            return queryset.filter(id__in=company_ids)
        return queryset


class CompanyAdmin(DjangoObjectActions, ExportActionMixin, admin.ModelAdmin):

    def reactivate(self, request, obj):
        obj.reactivate()

    def assume_identity(self, request, obj):
        request.user.profile.admin_switch_company(obj)
    assume_identity.short_description = "Change your company to this one."

    def update_usage_count(self, request, obj):
        obj.update_usage_count()
    update_usage_count.short_description = "Update monthly usage count to calculated value."

    def add_twilio_discount(self, request, obj):
        obj.add_twilio_discount()
        modify_freshsuccess_account.delay(obj.id)
    add_twilio_discount.short_description = "Enables the twilio discount for this company."

    change_actions = ('reactivate', 'assume_identity', 'update_usage_count', 'add_twilio_discount')
    list_display = ('name', 'subscription_status', 'invitation_code',
                    'subscription_signup_date', 'braintree_id',
                    'monthly_upload_limit', 'has_annual_subscription')
    search_fields = ('name', 'admin_name', 'subscription_id')
    list_filter = ('subscription_status', 'subscription_signup_date',
                   'invitation_code', AnnualUsersFilter)
    resource_class = CompanyResource

    def get_queryset(self, request):
        qs = super(CompanyAdmin, self).get_queryset(request)
        qs = qs.select_related('invitation_code')
        return qs


class CompanyChurnAdmin(admin.ModelAdmin):
    list_display = ('company', 'days_until_subscription', 'prospect_upload_percent')


class CompanyGoalAdmin(admin.ModelAdmin):
    list_display = ('company', 'start_date', 'end_date')


class CompanyUploadHistoryAdmin(admin.ModelAdmin):

    list_display = ('company', 'start_billing_date', 'end_billing_date', 'upload_count')
    search_fields = ('company__name',)


class DownloadHistoryAdmin(admin.ModelAdmin):
    list_display = ('company', 'created', 'status', 'download_type', 'file')
    search_fields = ('company__name', )


class InternalDNCAdmin(admin.ModelAdmin):
    list_display = ('added_datetime', 'phone_raw', 'company')
    search_fields = ('phone_raw', )


class LeadStageAdmin(admin.ModelAdmin):
    list_display = ('company', 'is_active', 'lead_stage_title', 'sort_order')


class UploadInternalDNCAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ('created', 'status', 'total_rows', 'last_row_processed')


class SMSPrefillTextAdmin(admin.ModelAdmin):
    list_display = ('company', 'question', 'message', 'sort_order')


class SubscriptionCancellationRequestAdmin(DjangoObjectActions, admin.ModelAdmin):

    def fulfill(self, request, obj):
        obj.fulfill()
    fulfill.short_description = "Immediately fulfill a cancellation request."

    list_display = ('request_datetime', 'company', 'status', 'cancellation_reason')
    list_filter = ('status', 'request_datetime')
    search_fields = ('company__name',)

    fieldsets = (
        (None, {'fields': (
            'company', 'requested_by', 'status', 'cancellation_date')}),
        ('Requests', {'fields': (
            'cancellation_reason', 'cancellation_reason_text', 'discount', 'pause', 'new_plan')}),
    )

    change_actions = ('fulfill',)
    list_select_related = ('company',)


class RoiStatAdmin(admin.ModelAdmin):
    search_fields = ('company__name',)

    def pm_skip_trace(self, obj):
        if not obj.profit_margin_skip_trace:
            return

        return f'{int(obj.profit_margin_skip_trace)}%'

    def pm_overall(self, obj):
        if not obj.profit_margin_lead_sherpa:
            return

        return f'{int(obj.profit_margin_lead_sherpa)}%'

    list_display = (
        'company',
        'period_start',
        'period_end',
        'revenue_subscription',
        'revenue_skip_trace',
        'revenue_additional_uploads',
        'revenue_other',
        'pm_skip_trace',
        'pm_overall',
    )


class UpdateMonthlyUploadLimitAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ['company', 'update_date', 'new_monthly_upload_limit', 'status']


class ZapierWebhookAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ['created', 'company', 'name', 'webhook_url', 'status']


class CompanyPodioCrmAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ['company', 'access_token']


class PodioFieldMappingAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ['company']


class CompanyPropStackFilterSettingsAdmin(admin.ModelAdmin):
    list_display = ['company', 'filter_name', 'created_by']


admin.site.register(Company, CompanyAdmin)
admin.site.register(CompanyChurn, CompanyChurnAdmin)
admin.site.register(DownloadHistory, DownloadHistoryAdmin)
admin.site.register(InternalDNC, InternalDNCAdmin)
admin.site.register(LeadStage, LeadStageAdmin)
admin.site.register(UploadInternalDNC, UploadInternalDNCAdmin)
admin.site.register(SMSPrefillText, SMSPrefillTextAdmin)
admin.site.register(SubscriptionCancellationRequest, SubscriptionCancellationRequestAdmin)
admin.site.register(RoiStat, RoiStatAdmin)
admin.site.register(UpdateMonthlyUploadLimit, UpdateMonthlyUploadLimitAdmin)
admin.site.register(ZapierWebhook, ZapierWebhookAdmin)
admin.site.register(CompanyGoal, CompanyGoalAdmin)
admin.site.register(CompanyUploadHistory, CompanyUploadHistoryAdmin)
admin.site.register(TelephonyConnection)
admin.site.register(CompanyPodioCrm, CompanyPodioCrmAdmin)
admin.site.register(PodioFieldMapping, PodioFieldMappingAdmin)
admin.site.register(CompanyPropStackFilterSettings, CompanyPropStackFilterSettingsAdmin)
