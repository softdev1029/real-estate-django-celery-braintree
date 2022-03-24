from rest_framework import serializers

from ..models.provider import Provider


class ProviderSerializer(serializers.ModelSerializer):
    """
    Provide Provider specific information such as settings and capabilities.
    """
    excluded_carriers = serializers.StringRelatedField(many=True)

    class Meta:
        model = Provider
        fields = [
            'id',
            'managed',
            'sms_market_minimum',
            'new_market_number_count',
            'messages_per_phone_per_day',
            'opt_out_language',
            'excluded_carriers',
        ]
