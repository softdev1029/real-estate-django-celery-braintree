from django.contrib import admin

from .models import Address, Property


class AddressAdmin(admin.ModelAdmin):
    pass


class PropertyAdmin(admin.ModelAdmin):
    pass


admin.site.register(Address, AddressAdmin)
admin.site.register(Property, PropertyAdmin)
