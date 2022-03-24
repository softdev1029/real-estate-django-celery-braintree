from django.contrib import admin

from .models import Call


class CallAdmin(admin.ModelAdmin):
    list_display = ('id', 'start_time', 'to_number', 'from_number')
    search_fields = ('call_session_id', 'call_control_id', 'from_number')


admin.site.register(Call, CallAdmin)
