from rest_framework import serializers

from accounts.serializers import SherpaUserSerializer
from .models import UploadSkipTrace


class UploadSkipTraceSerializer(serializers.ModelSerializer):
    created_by = SherpaUserSerializer()
    cost = serializers.SerializerMethodField()

    def get_cost(self, obj):
        return obj.cost_formatted

    class Meta:
        model = UploadSkipTrace
        fields = (
            "id",
            "cost",
            "existing_match_savings",
            "estimate_range",
            "hit_rate",
            "last_row_processed",
            "total_rows",
            "uploaded_filename",
            "upload_start",
            "upload_end",
            "status",
            "total_existing_matches",
            "total_hits",
            "total_billable_hits",
            "upload_error",
            "created_by",
            "company",
            "suppress_against_database",
            "push_to_campaign_status",
            "push_to_campaign_percent",
            "push_to_campaign_campaign_id",
            "push_to_campaign_campaign_name",
        )


class PushToCampaignGetSerializer(serializers.ModelSerializer):
    """
    Get data needed prior to pushing to campaign.
    """
    estimated_push_rows = serializers.IntegerField(read_only=True)
    estimated_new_prospects = serializers.IntegerField(read_only=True)

    class Meta:
        model = UploadSkipTrace
        fields = ("estimated_push_rows", "estimated_new_prospects")


class UploadSkipTraceMapFieldsRequestSerializer(serializers.Serializer):
    """
    Used just for documentation to show the required payload for mapping fields via Flatfile.
    """
    headers_matched = serializers.JSONField()
    valid_data = serializers.JSONField()
    uploaded_filename = serializers.CharField()
    property_tag_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True)

    class Meta:
        fields = ('headers_matched', 'valid_data', 'file_name', 'property_tag_ids')


class UploadSkipTraceSingleRequestSerializer(serializers.Serializer):
    """
    Used just for documentation to show the required payload for running single skip trace.
    """
    property_only = serializers.BooleanField()
    property_address = serializers.CharField()
    property_city = serializers.CharField()
    property_state = serializers.CharField()
    property_zip = serializers.CharField()
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    mailing_address = serializers.CharField(required=False)
    mailing_city = serializers.CharField(required=False)
    mailing_state = serializers.CharField(required=False)
    mailing_zip = serializers.CharField(required=False)

    class Meta:
        fields = (
            'property_only',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'first_name',
            'last_name',
            'mailing_address',
            'mailing_city',
            'mailing_state',
            'mailing_zip',
        )


class UploadSkipTraceResponseSerializer(serializers.ModelSerializer):
    """
    Used  for sending a response when uploading a skip trace.
    """
    class Meta:
        model = UploadSkipTrace
        fields = ('id', 'estimate_range', 'uploaded_filename', 'total_rows', 'property_tags')


class PushToCampaignSerializer(serializers.Serializer):
    campaign = serializers.IntegerField(required=True, help_text='id of the campaign to push to')
    import_type = serializers.CharField(required=True, help_text='Valid values are: "all", "new"')

    def validate_import_type(self, value):
        valid_values = ['all', 'new']
        if value not in valid_values:
            raise serializers.ValidationError(
                f'Invalid choice for `importType`. Valid values are {", ".join(valid_values)}')
        return value
