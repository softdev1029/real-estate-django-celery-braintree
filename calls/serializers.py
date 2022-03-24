from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .models import Call


class CallSerializer(serializers.ModelSerializer):
    """
    Serializer for call log purposes.
    """
    from_number = serializers.CharField(required=False, allow_null=True)
    prospect_name = serializers.CharField(source='prospect.get_full_name', read_only=True)
    agent_name = serializers.CharField(source='agent_profile.fullname', read_only=True)
    duration = serializers.IntegerField(read_only=True)
    recording = serializers.SerializerMethodField()
    call_type = serializers.CharField(source='get_call_type_display', read_only=True)

    class Meta:
        model = Call
        fields = (
            'from_number',
            'to_number',
            'start_time',
            'end_time',
            'prospect',
            'duration',
            'prospect_name',
            'agent_name',
            'recording',
            'call_type',
        )

        read_only_fields = (
            'duration',
            'prospect_name',
            'agent_name',
            'recording',
            'call_type',
        )

    def validate_prospect(self, prospect):
        request = self.context.get('request')
        if prospect.company_id != request.user.profile.company_id:
            raise ValidationError("Prospect could not be found.")
        return prospect

    def get_recording(self, call):
        if call.recording:
            return call.recording.url
        return None
