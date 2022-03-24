from django_object_actions import DjangoObjectActions
from import_export.admin import ExportActionMixin

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.utils.html import format_html


from sherpa.models import (
    LitigatorCheck, LitigatorList, LitigatorReportQueue, Prospect,
    UploadLitigatorCheck, UploadLitigatorList)
from .forms import LitigatorUploadCustomAddForm
from .resources import LitigatorListResource
from .tasks import upload_litigator_list_task


class LitigatorListAdmin(ExportActionMixin, admin.ModelAdmin):
    list_display = ('created', 'phone', 'type')
    list_filter = ['type']
    search_fields = ('phone',)
    resource_class = LitigatorListResource

    def has_change_permission(self, request, obj=None):
        if request.user.is_authenticated and request.user.is_staff \
                and request.user.is_superuser:
            return True

    def has_module_permission(self, request):
        return True


class UploadLitigatorListAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('created', 'status', 'total_rows', 'last_row_processed', 'last_numbers_saved',
                    'confirmation_email_sent')
    raw_id_fields = ('created_by',)
    change_actions = ('resend_to_task',)
    list_filter = ('status',)

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            # Custom class to pass request object
            class LitigatorFormWithRequest(LitigatorUploadCustomAddForm):
                def __new__(cls, *args, **kwargs):
                    kwargs['request'] = request
                    return LitigatorUploadCustomAddForm(*args, **kwargs)
            kwargs['form'] = LitigatorFormWithRequest
        return super().get_form(request, obj=obj, **kwargs)

    def resend_to_task(self, request, obj):
        upload_litigator_list_task.apply_async([obj.id], countdown=2)


class UploadLitigatorCheckAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = ('created', 'status', 'total_rows', 'last_row_processed')


class LitigatorCheckAdmin(admin.ModelAdmin):
    raw_id_fields = ('upload_litigator_check',)
    search_fields = ('phone1', 'phone2', 'phone3')
    list_display = ('created', 'validated_property_status', 'phone1', 'phone2', 'phone3',
                    'litigator_type', 'fullname')


class StatusFilter(admin.SimpleListFilter):
    """
    Status filter for LitigationReportQueue.  Forces 'pending' to be default filter when none have
    been selected.
    """
    title = 'Status'

    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return (
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('declined', 'Declined'),
            ('all', 'All'),
        )

    def choices(self, cl):
        for lookup, title in self.lookup_choices:
            is_all = not self.value() and lookup == LitigatorReportQueue.Status.PENDING
            yield {
                'selected': True if is_all else self.value() == lookup,
                'query_string': cl.get_query_string({
                    self.parameter_name: lookup,
                }, []),
                'display': title,
            }

    def queryset(self, request, queryset):
        if not self.value():
            return queryset.filter(status=LitigatorReportQueue.Status.PENDING)
        elif self.value() != 'all':
            return queryset.filter(status=self.value())
        return queryset.all()


class LitigatorReportQueueAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('prospect', 'get_phone', 'status', 'created')
    search_fields = ('prospect__phone_raw', 'prospect__company__name')
    list_filter = (StatusFilter,)
    fieldsets = (
        (None, {'fields': ('phone', 'reason', 'conversation_link')}),
        ('Prospect', {'fields': ('get_prospect_convo', 'get_phone', 'get_last_message')}),
        ('Reporter', {'fields': ('get_reporter', 'created')}),
        ('Result', {'fields': ('status', 'handled_by', 'handled_on')}),
    )

    readonly_fields = (
        'get_reporter',
        'get_prospect_convo',
        'get_last_message',
        'status',
        'created',
        'get_phone',
        'handled_by',
        'handled_on',
    )
    change_actions = ('approve', 'decline')

    def save_model(self, request, obj, form, change):
        phone_number = request.POST.get('phone').replace('-', '')
        obj.prospect = Prospect.objects.get(phone_raw=phone_number)
        obj.prospect.save()
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request, obj=None):
        if request.user.is_authenticated and request.user.is_staff \
                and request.user.is_superuser:
            return True

    def has_module_permission(self, request):
        return True

    def get_prospect_convo(self, obj):
        return format_html(
            "<a href='{url}' target='_blank'>{name}</a>",
            url=obj.prospect.public_url,
            name=obj.prospect,
        )
    get_prospect_convo.short_description = 'Prospect'

    def get_phone(self, obj):
        return obj.prospect.phone_display
    get_phone.short_description = 'Phone'
    get_phone.admin_order_field = 'prospect.phone_raw'

    def get_last_message(self, obj):
        return obj.prospect.display_message.message
    get_last_message.short_description = 'Last Message'

    def get_reporter(self, obj):
        return f"{obj.submitted_by.get_full_name()}"
    get_reporter.short_description = 'User'
    get_reporter.admin_order_field = 'submitted_by'

    def approve(self, request, obj):
        if obj.status != LitigatorReportQueue.Status.APPROVED:
            obj.approve(request.user)
        return self._go_back_to_list(request)

    def decline(self, request, obj):
        if obj.status != LitigatorReportQueue.Status.DECLINED:
            obj.decline(request.user)
        return self._go_back_to_list(request)

    def _go_back_to_list(self, request):
        url = request.build_absolute_uri("/admin/sherpa/litigatorreportqueue/")
        return HttpResponseRedirect(url)


admin.site.register(LitigatorCheck, LitigatorCheckAdmin)
admin.site.register(UploadLitigatorCheck, UploadLitigatorCheckAdmin)
admin.site.register(LitigatorList, LitigatorListAdmin)
admin.site.register(UploadLitigatorList, UploadLitigatorListAdmin)
admin.site.register(LitigatorReportQueue, LitigatorReportQueueAdmin)
