from django_object_actions import DjangoObjectActions

from django import forms
from django.contrib import admin
from django.db.models import Case, F, prefetch_related_objects, Sum, Value, When
from django.urls import reverse
from django.utils.html import format_html

from sherpa.models import (
    Campaign,
    CampaignAccess,
    StatsBatch,
)
from sms.admin import SMSMessageResultInlineAdmin
from .models import AutoDeadDetection, CampaignIssue, DirectMailCampaign, DirectMailOrder


class StatsBatchInlineAdmin(admin.TabularInline):
    model = StatsBatch
    fields = ('batch_number', 'send_attempt', 'delivered', 'received', 'total_skipped',
              'last_send_utc')
    ordering = ('-batch_number',)
    can_delete = False
    readonly_fields = ('total_skipped', 'batch_number', 'send_attempt', 'delivered', 'received')
    show_change_link = True
    max_num = 5

    def has_add_permission(self, request, obj):
        return False


class CampaignAdminForm(forms.ModelForm):
    """
    Campaign admin has a lot of dropdown fields based off of `ForeignKey`.  We need to limit
    each dropdown to only show values that are owned by the company each campaign belongs to.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self.instance, 'company'):
            if not self.fields:
                return
            company = self.instance.company
            prefetch_related_objects(
                [company],
                'smstemplate_set',
                'webhooks',
            )
            self.fields['zapier_webhook'].queryset = company.webhooks.all()
            self.fields['owner'].queryset = company.userprofile_set.all()


class CampaignTypeFilter(admin.SimpleListFilter):
    """
    This class is used for filtering campaigns based on the type(SMS/Directmail)
    in django admin panel for company model.
    """

    title = "Campaign type"
    parameter_name = "campaign_type"

    def lookups(self, request, model_admin):
        return (
            ("SMS", 'SMS'),
            ("DirectMail", 'DirectMail'),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if not self.value():
            return queryset
        if self.value().lower() == "sms":
            return queryset.filter(is_direct_mail=False)
        elif self.value().lower() == "directmail":
            return queryset.filter(is_direct_mail=True)
        return queryset


class CampaignAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('name', 'company', 'market', 'total_sent',
                    'created_date', 'is_archived')
    search_fields = ('name', 'company__name')
    readonly_fields = (
        'company',
        'market',
        'health',
        'created_by',
        'is_default',
        'is_archived',
        'is_followup',
        'retain_numbers',
        'has_unread_sms',
        'has_priority',
        'total_priority',
        'total_sms_followups',
        'total_skipped',
        'total_dnc_count',
        'total_sms_sent_count',
        'total_sms_received_count',
        'total_wrong_number_count',
        'total_auto_dead_count',
        'total_initial_sent_skipped',
        'total_mobile',
        'total_landline',
        'total_phone_other',
        'total_intial_sms_sent_today_count',
        'total_leads',
        'has_delivered_sms_only_count',
        'sms_template',
        'followup_link',
    )
    change_actions = ('update_progress', 'update_import_stats', 'recalculate_stats')
    inlines = (StatsBatchInlineAdmin,)
    form = CampaignAdminForm
    fieldsets = (
        (None, {
            'fields': ('name', 'company', 'market', 'health', 'timezone', 'owner', 'created_by'),
        }),
        ('Settings', {
            'fields': (
                'is_default',
                'is_archived',
                'is_followup',
                'followup_link',
                'retain_numbers',
                'skip_trace_cost_per_record',
                'call_forward_number',
                'skip_prospects_who_messaged',
                'podio_push_email_address',
                'zapier_webhook',
                'sms_template',
            ),
        }),
        ('Metrics', {
            'fields': (
                'has_unread_sms',
                'has_priority',
                'total_priority',
                'total_sms_followups',
                'total_skipped',
                'total_dnc_count',
                'total_sms_sent_count',
                'total_sms_received_count',
                'total_wrong_number_count',
                'total_auto_dead_count',
                'total_initial_sent_skipped',
                'total_mobile',
                'total_landline',
                'total_phone_other',
                'total_intial_sms_sent_today_count',
                'total_leads',
                'has_delivered_sms_only_count',
            ),
        }),
        (None, {
            'fields': ('issues',),
        }),
    )
    list_filter = (CampaignTypeFilter,)
    list_select_related = ('market', 'company')

    def update_progress(self, request, obj):
        obj.update_progress()
    update_progress.short_description = ("Sync the campaign's progress with its sent/skipped "
                                         "messages.")

    def update_import_stats(self, request, obj):
        obj.update_campaign_stats()
    update_import_stats.short_description = ("Sync the campaign's import stats as they are "
                                             "sometimes incorrect.")

    def recalculate_stats(self, request, obj):
        from campaigns.tasks import recalculate_stats
        recalculate_stats(obj.id)
    recalculate_stats.short_description = ("Recalculate stats from scratch, might take a while."
                                           "Recalculated stats might have minor inconsistencies "
                                           "USE ONLY IF STATS ARE ALREADY INCORRECT")

    def followup_link(self, obj):
        if not obj.followup_from:
            return ''
        url = reverse("admin:sherpa_campaign_change", args=(obj.followup_from.pk,))
        return format_html(f'<a href="{url}">{obj.followup_from.name}</a>')

    def total_sent(self, obj):
        return obj.sent
    total_sent.admin_order_field = "sent"

    def get_queryset(self, request):
        qs = (
            super(CampaignAdmin, self)
            .get_queryset(request)
            .annotate(
                send_att=Sum("statsbatch__send_attempt"),
                skip=F("campaign_stats__total_skipped"),
            )
            .annotate(
                sent=Case(
                    When(send_att=F("send_att"), then=F("send_att") - F("skip")),
                    default=Value(0),
                ),
            )
        )
        return qs


class CampaignAccessAdmin(admin.ModelAdmin):
    list_display = ('created_date', 'campaign', 'user_profile')


class StatsBatchAdmin(admin.ModelAdmin):
    raw_id_fields = ('campaign', 'market', 'parent_market')
    list_display = ('created_utc', 'campaign', 'batch_number', 'send_attempt', 'response_rate',
                    'delivered', 'received', 'received_dead_auto', 'total_skipped')
    inlines = (SMSMessageResultInlineAdmin,)


class AutoDeadDetectionAdmin(admin.ModelAdmin):
    list_display = ('message', 'score', 'marked_auto_dead')


class DirectMailInlineAdmin(admin.TabularInline):
    model = DirectMailCampaign
    max_num = 1

    can_delete = False
    show_change_link = True


class DirectMailOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id',
        'campaign',
        'company',
        'status',
        'drop_date',
        'record_count',
    )
    search_fields = ('order_id',)
    inlines = (DirectMailInlineAdmin,)

    def company(self, obj):
        if obj.campaign:
            return obj.campaign.company


class DirectMailOrderInlineAdmin(admin.TabularInline):
    model = DirectMailOrder
    max_num = 1

    can_delete = False
    show_change_link = True


class DirectMailCampaignAdmin(admin.ModelAdmin):
    list_display = (
        'campaign',
        'order_id_link',
        'company',
        'status',
        'drop_date',
        'record_count',
    )
    search_fields = ('order__order_id',)

    def order_id_link(self, obj):
        if not obj.order:
            return

        url = f"{reverse('admin:campaigns_directmailorder_changelist')}{obj.id}/"
        return format_html('<a href="{}">{}</a>', url, obj.order.order_id)

    order_id_link.short_description = "Order ID"

    def company(self, obj):
        if obj.campaign:
            return obj.campaign.company

    def status(self, obj):
        if obj.order:
            return obj.order.status

    def drop_date(self, obj):
        if obj.order:
            return obj.order.drop_date

    def record_count(self, obj):
        if obj.order:
            return obj.order.record_count


admin.site.register(Campaign, CampaignAdmin)
admin.site.register(DirectMailCampaign, DirectMailCampaignAdmin)
admin.site.register(DirectMailOrder, DirectMailOrderAdmin)
admin.site.register(CampaignAccess, CampaignAccessAdmin)
admin.site.register(StatsBatch, StatsBatchAdmin)
admin.site.register(CampaignIssue)
admin.site.register(AutoDeadDetection, AutoDeadDetectionAdmin)
