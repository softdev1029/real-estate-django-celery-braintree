from django.contrib import admin

from .models import Plan, Transaction


class TransactionAdmin(admin.ModelAdmin):
    list_display = ['dt_charged', 'company', 'type', 'amount_authorized', 'is_authorized',
                    'is_charged', 'amount_charged', 'failure_reason', 'transaction_id',
                    'created_with_sync']


class PlanAdmin(admin.ModelAdmin):
    list_display = (
        'braintree_id',
        'max_monthly_prospect_count',
        'first_market_phone_number_count',
    )


admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Plan, PlanAdmin)
