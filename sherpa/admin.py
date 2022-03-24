# -*- coding: utf-8 -*-


from django.contrib import admin

from .models import PhoneType, SiteSettings, SupportLink


class PhoneTypeAdmin(admin.ModelAdmin):
    list_display = ['checked_datetime', 'phone', 'type', 'campaign', 'company']
    search_fields = ['phone']
    raw_id_fields = ('campaign', 'company')


admin.site.register(PhoneType, PhoneTypeAdmin)
admin.site.register(SupportLink)
admin.site.register(SiteSettings)
