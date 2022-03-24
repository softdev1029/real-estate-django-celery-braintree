from django.utils import timezone
from rest_framework import serializers

from sherpa.models import PhoneNumber


class PhoneNumberSerializer(serializers.ModelSerializer):
    # Change the source of datetimes as the field name ideally should change to remove the `_utc`.
    last_send = serializers.DateTimeField(source='last_send_utc')
    last_received = serializers.DateTimeField(source='last_received_utc')

    class Meta:
        model = PhoneNumber
        fields = (
            'id',
            'created',
            'phone',
            'market',
            'status',
            'last_send',
            'last_received',
            'health',
            'provider',
        )
        read_only_fields = ('created', 'phone', 'market', 'last_send', 'last_received', 'provider')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        try:
            if self.context['request'].method in ['GET']:
                self.fields['status'] = serializers.SerializerMethodField()
        except KeyError:
            pass

    def get_status(self, obj):
        cooldown = obj.market.current_spam_cooldown_period_end
        if obj.status == PhoneNumber.Status.ACTIVE and cooldown and cooldown > timezone.now():
            return 'cooldown'
        return obj.status
