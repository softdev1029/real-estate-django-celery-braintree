from django_object_actions import DjangoObjectActions
from import_export.admin import ImportExportActionModelAdmin
from rangefilter.filter import DateRangeFilter

from django import forms
from django.contrib import admin

from .models import SkipTraceDailyStats, SkipTraceProperty, UploadSkipTrace
from .resources import SkipTraceDailyStatsResource


class SkipTracePropertyAdmin(admin.ModelAdmin):
    raw_id_fields = ('upload_skip_trace',)
    search_fields = ('submitted_owner_last_name',)
    list_display = (
        'upload_skip_trace', 'deceased', 'created', 'submitted_owner_first_name',
        'validated_mailing_status', 'validated_property_status',
        'validated_returned_property_status', 'has_hit', 'no_hit_calculated', 'returned_phone_1',
        'returned_email_1', 'returned_address_1', 'is_existing_match', 'synced_push_to_campaign')


class UploadSkipTraceAdminForm(forms.ModelForm):
    """
    UploadSkipTrace admin doesn't have many dropdown fields relating to `ForiegnKeys` but the one
    it does have is quite sensitive.  We should limit billing transactional data to only show those
    belonging to the company each UploadSkipTrace is part of.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self.instance, 'company'):
            company = self.instance.company
            # If we're adding a new record in django admin we won't have a company and that's ok.
            if not company:
                return
            self.fields['push_to_campaign_transaction'].queryset = company.transaction_set.all()


class UploadSkipTraceAdmin(DjangoObjectActions, admin.ModelAdmin):
    def restart(self, request, obj):
        obj.restart()

    change_actions = ('restart',)
    search_fields = ('company__name',)
    list_filter = ('status', 'created')
    raw_id_fields = ('company', 'created_by', 'transaction')
    list_display = (
        'created', 'company', 'status', 'total_rows', 'last_row_processed',
        'email_confirmation_sent', 'push_to_campaign_status', 'total_hits', 'total_billable_hits')
    form = UploadSkipTraceAdminForm

    def get_queryset(self, request):
        qs = super(UploadSkipTraceAdmin, self).get_queryset(request)
        qs = qs.prefetch_related('company')
        return qs


class SkipTraceDailyStatsAdmin(ImportExportActionModelAdmin):
    resource_class = SkipTraceDailyStatsResource
    list_filter = (
        ('date', DateRangeFilter),
    )
    list_display = ('date', 'total_external_hits', 'total_internal_hits')


admin.site.register(SkipTraceDailyStats, SkipTraceDailyStatsAdmin)
admin.site.register(UploadSkipTrace, UploadSkipTraceAdmin)
admin.site.register(SkipTraceProperty, SkipTracePropertyAdmin)
