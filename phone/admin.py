from django_object_actions import DjangoObjectActions

from core import admin
from sherpa.models import PhoneNumber
from .models.carrier import Carrier
from .models.provider import Provider


class PhoneNumberAdmin(DjangoObjectActions, admin.ModelAdmin):

    def replace(self, request, obj):
        obj.replace()
    replace.short_description = "Replace the phone number with a new number in same market."

    def activate(self, request, obj):
        obj.activate()
    activate.short_description = "Activate this number and others stuck pending in same market."

    list_display = ('created', 'phone', 'market', 'status', 'company', 'provider', 'provider_id')
    search_fields = ('phone', 'market__name', 'company__name')
    raw_id_fields = ('market', 'company')
    list_filter = ('provider', 'status')
    change_actions = ('replace', 'activate')


class ProviderAdmin(admin.ReadOnlyAdmin):
    list_display = (
        'id',
        'priority',
        'managed',
        'sms_market_minimum',
        'new_market_number_count',
        'messages_per_phone_per_day',
    )


class CarrierAdmin(admin.ReadOnlyAdmin):
    list_display = ('id', 'carrier_keys')


admin.site.register(PhoneNumber, PhoneNumberAdmin)
admin.site.register(Carrier, CarrierAdmin)
admin.site.register(Provider, ProviderAdmin)
