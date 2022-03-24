from django_object_actions import DjangoObjectActions

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import prefetch_related_objects
from django.http import HttpResponseRedirect
from django.urls import path

from sherpa.models import Note, Prospect, UploadProspects
from .models import ProspectRelay, RelayNumber

User = get_user_model()


class ProspectAdminForm(forms.ModelForm):
    """
    Prospect admin has a lot of dropdown fields based off of `ForeignKey`.  We need to limit
    each dropdown to only show values that are owned by the company each prospect belongs to.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self.instance, 'company'):
            company = self.instance.company
            prefetch_related_objects(
                [company],
                'userprofile_set',
                'leadstage_set',
                'phone_numbers',
                'campaign_set',
                'market_set',
            )
            self.fields['qualified_lead_created_by'].queryset = User.objects.filter(
                profile__company=company,
            )
            self.fields['agent'].queryset = company.userprofile_set.all()
            self.fields['lead_stage'].queryset = company.leadstage_set.all()
            self.fields['cloned_from'].queryset = company.prospect_set.all()
            self.fields['sherpa_phone_number_obj'].queryset = company.phone_numbers.all()

            self.fields['campaigns'].queryset = company.campaign_set.all()
            self.fields['markets'].queryset = company.market_set.all()


class ProspectAdmin(admin.ModelAdmin):
    raw_id_fields = ('company',)
    list_display = (
        'created_date', 'validated_property_status', 'company', 'phone_raw', 'phone_type',
        'first_name', 'last_name', 'has_unread_sms', 'do_not_call')
    search_fields = ('last_name', 'property_address', 'phone_raw')
    form = ProspectAdminForm


class NoteAdmin(admin.ModelAdmin):
    list_display = ('created_date', 'text')


class UploadProspectsAdmin(DjangoObjectActions, admin.ModelAdmin):
    def restart(self, request, obj):
        obj.restart()

    change_actions = ('restart',)
    list_display = ('created',
                    'path',
                    'status',
                    'total_rows',
                    'new',
                    'existing',
                    'last_row_processed',
                    'exceeds_count',
                    'company',
                    'phone_1_number',
                    'phone_2_number',
                    'phone_3_number',
                    'upload_time',
                    )
    raw_id_fields = ('campaign',)
    search_fields = ('company__name',)
    list_filter = ('status', 'created')


class RelayNumberAdmin(DjangoObjectActions, admin.ModelAdmin):
    """
    Add button to purchase relay numbers and to release numbers.
    """
    change_list_template = "phone_management/relaynumber_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        my_urls = [path('purchase/', self.purchase)]
        return my_urls + urls

    def purchase(self, request):
        RelayNumber.purchase_numbers()
        self.message_user(request, "Finished purchasing up to 100 numbers.")
        return HttpResponseRedirect("../")

    purchase.short_description = "Purchase relay numbers"

    def release(self, request, obj):
        obj.release()
    release.short_description = "Release relay number."

    list_display = ('created', 'phone', 'status', 'provider_id')
    search_fields = ('phone',)
    list_filter = ('status',)
    change_actions = ('release',)


admin.site.register(Prospect, ProspectAdmin)
admin.site.register(Note, NoteAdmin)
admin.site.register(UploadProspects, UploadProspectsAdmin)
admin.site.register(RelayNumber, RelayNumberAdmin)
admin.site.register(ProspectRelay)
