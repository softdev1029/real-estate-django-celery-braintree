from rest_framework import serializers

from sherpa.models import AreaCodeState, Market


class MarketSerializer(serializers.ModelSerializer):
    area_code = serializers.CharField(required=False, source='area_code1')
    campaign_count = serializers.SerializerMethodField()
    total_initial_send_sms_daily_limit = serializers.IntegerField()

    def get_campaign_count(self, obj):
        return obj.active_campaigns.count()

    def validate_call_forwarding_number(self, value):
        """
        Check that call forwarding number is a valid number.
        """
        if not len(value) == 10 or not value.isdigit():
            raise serializers.ValidationError("Call forwarding number should be 10 digits.")
        return value

    class Meta:
        model = Market
        fields = (
            'id',
            'name',
            'is_active',
            'company',
            'campaign_count',
            'call_forwarding_number',
            'area_code',
            'total_intial_sms_sent_today_count',
            'total_initial_send_sms_daily_limit',
            'current_spam_cooldown_period_end',
        )


class ParentMarketSerializer(serializers.ModelSerializer):

    class Meta:
        model = AreaCodeState
        fields = ('id', 'city', 'state', 'is_open', 'area_code')


class MarketPurchaseRequestSerializer(serializers.Serializer):
    """
    Used just for documentation to show the required payload for purchasing a market.
    """
    area_code = serializers.CharField(max_length=3, required=True)
    market_name = serializers.CharField(max_length=255, required=True)
    call_forwarding_number = serializers.CharField(max_length=10, required=True)
    master_area_code_state_id = serializers.IntegerField()
    best_effort = serializers.BooleanField(required=False)

    class Meta:
        fields = (
            'area_code',
            'market_name',
            'call_forwarding_number',
            'master_area_code_state_id',
            'best_effort',
        )


class TelephonyMarketSerializer(serializers.Serializer):
    """
    Used just for documentation to show the required payload for creating/updating a Market based
    on the user's own telephony setup.
    """
    name = serializers.CharField(max_length=255, required=True)
    call_forwarding = serializers.CharField(max_length=10, required=True)
    numbers = serializers.ListField()
    provider_id = serializers.IntegerField()

    class Meta:
        fields = (
            'name',
            'call_forwarding_number',
            'phone_numbers',
            'provider',
        )


class PurchaseNumbersSerializer(serializers.Serializer):
    """
    Used just for they payload to accept a number purchase.
    """
    quantity = serializers.IntegerField(min_value=0)
    best_effort = serializers.BooleanField(required=False, default=False)


class AvailableNumbersSerializer(serializers.Serializer):
    """
    Response data for returning data about market number availability.
    """
    numbers = serializers.ListField()
    area_codes = serializers.DictField()
