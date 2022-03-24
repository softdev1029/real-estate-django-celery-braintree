from django.contrib import admin

from sherpa.models import (
    ReceiptSmsDirect,
    SMSMessage,
    SMSTemplate,
)
from .models import CarrierApprovedTemplate, DailySMSHistory


class SMSMessageResultInlineAdmin(admin.TabularInline):
    """
    Inline form to show results data.

    Need to use this approach to show results inline on a stats batch because it does not have a
    direct relation to `SMSResult`.
    """
    model = SMSMessage
    fields = ('provider_message_id', 'status', 'error_code')
    readonly_fields = ['status', 'error_code']

    def error_code(self, obj):
        return obj.result.error_code

    def status(self, obj):
        return obj.result.status

    def get_queryset(self, request):
        return super(SMSMessageResultInlineAdmin, self).get_queryset(
            request).prefetch_related('result')


class ReceiptSmsDirectAdmin(admin.ModelAdmin):
    search_fields = ('phone_raw',)
    list_display = ('sent_date', 'phone_raw', 'company')


class SMSMessageAdmin(admin.ModelAdmin):
    list_display = ('dt_local', 'company', 'from_number', 'to_number', 'unread_by_recipient',
                    'prospect', 'message_status', 'from_prospect', 'has_second_send_attempt')
    search_fields = ('contact_number', 'our_number')
    raw_id_fields = ('prospect', 'user', 'response_from_rep', 'initial_message_sent_by_rep',
                     'campaign', 'company')


class SMSTemplateAdmin(admin.ModelAdmin):
    list_display = ('created', 'template_name', 'company', 'message')


class DailySMSHistoryAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_attempted', 'delivery_rate', 'error_rate')


class CarrierApprovedTemplateAdmin(admin.ModelAdmin):
    list_display = ('id', 'is_active', 'message', 'alternate_message')
    list_filter = ('is_verified', 'is_active')


admin.site.register(SMSMessage, SMSMessageAdmin)
admin.site.register(ReceiptSmsDirect, ReceiptSmsDirectAdmin)
admin.site.register(SMSTemplate, SMSTemplateAdmin)
admin.site.register(DailySMSHistory, DailySMSHistoryAdmin)
admin.site.register(CarrierApprovedTemplate, CarrierApprovedTemplateAdmin)
