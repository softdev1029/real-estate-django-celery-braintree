from django_object_actions import DjangoObjectActions

from django.conf import settings
from django.contrib import admin, messages

from phone.tasks import update_pending_phone_number
from phone.utils import process_number_order
from sherpa.models import AreaCodeState, Market, PhoneNumber
from .tasks import update_numbers


class AreaCodeStateAdmin(admin.ModelAdmin):
    search_fields = ['state', 'area_code', 'city']
    list_filter = ['parent_market']
    list_display = ['city', 'state', 'area_code', 'parent_market', 'market_cap']
    readonly_fields = ['market_count']


class MarketAdmin(DjangoObjectActions, admin.ModelAdmin):

    def deactivate(self, request, obj):
        obj.deactivate()
    deactivate.short_description = ("Deactivate the market - you'll still need to modify braintree "
                                    "subscriptions, but the numbers will be released and the user "
                                    "won't be able to select the market.")

    def claim_numbers(self, request, obj):
        update_numbers.delay(obj.id, {'messaging_profile_id': obj.messaging_profile_id})

    def set_connections(self, request, obj):
        update_numbers.delay(obj.id, {'connection_id': settings.TELNYX_CONNECTION_ID})

    def update_pending(self, request, obj):
        """
        Update the pending numbers to be active.

        We need to call the individual task for these as when we run for the whole market the telnyx
        api client isn't able to filter properly due to a bug.
        """
        for phone_number in obj.phone_numbers.filter(status=PhoneNumber.Status.PENDING):
            update_pending_phone_number.delay(phone_number.id)

    claim_numbers.short_description = "Assign all active market numbers to its messaging profile."
    set_connections.short_description = "Assign a voice connection to all active market numbers."
    update_pending.short_description = "Assign the provider id from Telnyx and activate number."

    def _create_number_order(self, request, obj, quantity):
        """
        Purchase a given amount of phone numbers for the market if they're available.
        """
        if obj.name == 'Twilio':
            return

        client = obj.company.messaging_client
        available_response = client.get_available_numbers(obj.area_code1, limit=quantity)
        available_list = [instance.get('phone_number') for instance in available_response['data']]

        if len(available_list) < quantity:
            messages.error(request, 'There are only {} numbers available for {}.'.format(
                len(available_list),
                obj.area_code1,
            ))
        else:
            process_number_order(obj, available_list)

    def purchase_number(self, request, obj):
        self._create_number_order(request, obj, 1)
    purchase_number.short_description = "Purchase a phone number if it's available."

    def purchase_10(self, request, obj):
        self._create_number_order(request, obj, 10)
    purchase_10.short_description = "Purchase 10 numbers for this market, if they're available."

    def purchase_20(self, request, obj):
        self._create_number_order(request, obj, 20)
    purchase_20.short_description = "Purchase 20 numbers for this market, if they're available."

    list_display = ('created_date', 'name', 'company', 'is_active', 'parent_market',
                    'total_intial_sms_sent_today_count', 'total_initial_send_sms_daily_limit',
                    'total_phone_active', 'total_phone_inactive', 'included_phones', 'area_code1',
                    'area_code2')
    raw_id_fields = ('parent_market', 'company', 'one_time_transaction')
    search_fields = ('name', 'company__name', 'parent_market__city', 'parent_market__state',
                     'messaging_profile_id')

    change_actions = (
        'deactivate',
        'purchase_20',
        'purchase_10',
        'purchase_number',
        'claim_numbers',
        'set_connections',
        'update_pending',
    )


admin.site.register(AreaCodeState, AreaCodeStateAdmin)
admin.site.register(Market, MarketAdmin)
