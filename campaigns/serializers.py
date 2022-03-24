from datetime import timedelta

from rest_flex_fields.serializers import FlexFieldsSerializerMixin

from rest_framework import serializers

from accounts.serializers import SherpaUserSerializer
from markets.serializers import MarketSerializer
from properties.models import PropertyTag
from properties.serializers import AddressSerializer
from sherpa.models import (
    Campaign, CampaignProspect, LeadStage, Prospect, StatsBatch, UploadProspects, ZapierWebhook)
from .models import (
    CampaignDailyStats,
    CampaignIssue,
    CampaignNote,
    CampaignTag,
    DirectMailCampaign,
    DirectMailCampaignStats,
    DirectMailOrder,
    DirectMailReturnAddress,
    DirectMailTracking,
)


class StatsBatchSerializer(serializers.ModelSerializer):
    skip_details = serializers.DictField()

    class Meta:
        model = StatsBatch
        fields = [
            'batch_number',
            'response_rate',
            'delivered_percent',
            'send_attempt',
            'total_skipped',
            'skip_details',
            'last_send',
        ]
        read_only_fields = ['skip_details']


class CampaignTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignTag
        fields = ('name',)


class DirectMailOrderSerializer(serializers.ModelSerializer):
    """
    Serializer to return DirectMailOrder
    """
    note_for_processor = serializers.CharField(required=False)
    lock_date = serializers.SerializerMethodField()

    def get_lock_date(self, obj):
        lock_date = None
        if obj.drop_date:
            lock_date = obj.drop_date - timedelta(days=3)
        return lock_date

    class Meta:
        model = DirectMailOrder
        fields = (
            'id',
            'creative_type',
            'template',
            'note_for_processor',
            'order_id',
            'status',
            'error',
            'record_count',
            'drop_date',
            'scheduled_date',
            'lock_date',
        )
        read_only_fields = (
            'id',
            'order_id',
            'status',
            'error',
            'record_count',
            'scheduled_date',
            'lock_date',
        )


class DirectMailCampaignTrackingSerializer(serializers.ModelSerializer):
    """
    Return tracking information.
    """

    class Meta:
        model = DirectMailTracking
        fields = (
            'delivery_rate',
            'undeliverable_rate',
            'record_count',
            'not_scanned',
            'early',
            'on_time',
            'late',
            'en_route',
            'total_undelivered',
            'total_delivered',
        )

        read_only_fields = (
            'delivery_rate',
            'undeliverable_rate',
            'record_count',
            'not_scanned',
            'early',
            'on_time',
            'late',
            'en_route',
            'total_undelivered',
            'total_delivered',
        )


class DirectMailCampaignAggregateStatsSerializer(serializers.ModelSerializer):
    """
    Return tracking information.
    """

    class Meta:
        model = DirectMailOrder
        fields = (
            'total_delivered',
            'delivered_rate',
            'total_returned',
            'returned_rate',
            'total_redirected',
            'redirected_rate',
        )

        read_only_fields = (
            'total_delivered',
            'delivered_rate',
            'total_returned',
            'returned_rate',
            'total_redirected',
            'redirected_rate',
        )


class DirectMailReturnAddressSerializer(serializers.ModelSerializer):
    """
    Serializer to return DirectMailReturnAddress
    """
    address = AddressSerializer()

    class Meta:
        model = DirectMailReturnAddress
        fields = (
            'id',
            'from_user',
            'first_name',
            'last_name',
            'address',
            'phone',
        )


class DirectMailCampaignResponseSerializer(serializers.ModelSerializer):
    """
    Serializer to create DirectMailCampaign
    """
    order = DirectMailOrderSerializer()
    return_address = DirectMailReturnAddressSerializer()

    class Meta:
        model = DirectMailCampaign
        fields = (
            'id',
            'campaign',
            'order',
            'budget_per_order',
            'return_address',
            'is_locked',
            'total_recipients',
            'cost',
        )

        read_only_fields = (
            'total_recipients',
            'cost',
        )


class CampaignListSerializer(serializers.ModelSerializer):
    """
    Slim serializer to show campaign data on the list page.
    """
    access = serializers.ListField(
        source="access_list",
        required=False,
        help_text="Array of user profile ids",
    )
    market = MarketSerializer()
    created_by = SherpaUserSerializer()
    priority_count = serializers.IntegerField(
        source='campaign_stats.total_priority',
        required=False,
        read_only=True,
    )
    total_initial_sent_skipped = serializers.IntegerField(
        source='campaign_stats.total_initial_sent_skipped',
    )
    total_mobile = serializers.IntegerField(source='campaign_stats.total_mobile')
    total_leads = serializers.IntegerField(source='campaign_stats.total_leads')
    directmail = DirectMailCampaignResponseSerializer(required=False)

    class Meta:
        model = Campaign
        fields = (
            'id',
            'owner',
            'company',
            'created_by',
            'directmail',
            'name',
            'health',
            'is_archived',
            'is_direct_mail',
            'created_date',
            'total_leads',
            'priority_count',
            'percent_complete',
            'has_unread_sms',
            'total_initial_sent_skipped',
            'total_mobile',
            'market',
            'zapier_webhook',
            'call_forward_number',
            'access',
            'podio_push_email_address',
            'skip_prospects_who_messaged',
        )

        read_only_fields = ('is_direct_mail',)


class DirectMailCreateCampaignSerializer(serializers.ModelSerializer):
    """
    Slim serializer to create Campaign for DirectMail
    """
    access = serializers.ListField(
        source="access_list",
        required=False,
        help_text="Array of user profile ids",
    )
    created_by = SherpaUserSerializer()

    class Meta:
        model = Campaign
        fields = (
            'id',
            'owner',
            'company',
            'created_by',
            'name',
            'health',
            'is_archived',
            'is_direct_mail',
            'created_date',
            'zapier_webhook',
            'call_forward_number',
            'access',
            'podio_push_email_address',
        )

        read_only_fields = ('is_direct_mail',)


class CampaignSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    """
    Full serializer for campaigns, with all of its data. This is a fairly intensive data load, so
    it's only used once the user is viewing a single campaign detail.
    """
    priority_count = serializers.IntegerField(
        source='campaign_stats.total_priority',
        required=False,
        read_only=True,
    )
    total_initial_sent_skipped = serializers.IntegerField(
        source='campaign_stats.total_initial_sent_skipped',
        read_only=True,
    )
    total_mobile = serializers.IntegerField(source='campaign_stats.total_mobile', read_only=True)
    total_leads = serializers.IntegerField(source='campaign_stats.total_leads', read_only=True)
    current_batch = StatsBatchSerializer(read_only=True)

    # DEPRECATED: `latest_batch*` fields will be removed and `current_batch` should be used instead.
    latest_batch_number = serializers.SerializerMethodField(
        help_text='DEPRECATED: use the `current_batch` object instead.')
    latest_batch_attempts = serializers.SerializerMethodField(
        help_text='DEPRECATED: use the `current_batch` object instead.')
    access = serializers.ListField(
        source="access_list",
        required=False,
        help_text="Array of user profile ids",
    )
    messages_sent_today = serializers.IntegerField(
        source='market.total_intial_sms_sent_today_count',
        required=False,
    )
    daily_send_limit = serializers.IntegerField(
        source='market.total_initial_send_sms_daily_limit',
        required=False,
    )
    directmail = DirectMailCampaignResponseSerializer(required=False)

    expandable_fields = {
        'market': ('markets.serializers.MarketSerializer', {}),
        'created_by': ('accounts.serializers.SherpaUserSerializer', {}),
    }

    def validate_zapier_webhook(self, value):
        if value and value.status == ZapierWebhook.Status.INACTIVE:
            raise serializers.ValidationError('Cannot save inactive Zapier webhook')
        return value

    def to_representation(self, instance):
        """
        Return some relational fields expanded to match list view.
        """
        data = super().to_representation(instance)
        data['created_by'] = SherpaUserSerializer(instance.created_by).data
        data['market'] = MarketSerializer(instance.market).data
        return data

    def get_latest_batch_number(self, obj):
        return obj.current_batch_status[0]

    def get_latest_batch_attempts(self, obj):
        return obj.current_batch_status[1]

    class Meta:
        model = Campaign
        fields = [
            'id',
            'name',
            'company',
            'market',
            'is_default',
            'is_archived',
            'created_date',
            'created_by',
            'directmail',
            'total_prospects',
            'total_leads',
            'health',
            'owner',
            'has_unread_sms',
            'priority_count',
            'podio_push_email_address',
            'zapier_webhook',
            'sms_template',
            'block_reason',
            'latest_batch_number',
            'latest_batch_attempts',
            'messages_sent_today',
            'daily_send_limit',
            'call_forward_number',
            'access',
            'current_batch',
            'percent_complete',
            'upload_prospect_running',
            'total_initial_sent_skipped',
            'total_mobile',
            'list_quality_score',
            'can_create_followup',
            'skip_prospects_who_messaged',
            'is_direct_mail',
        ]
        read_only_fields = (
            'progress',
            'total_prospects',
            'created_by',
            'company',
            'percent_complete',
            'upload_prospect_running',
            'is_direct_mail',
        )

    def validate_access(self, value):
        """
        Validate that the user ids passed in belong to the request user's company.
        """
        company = self.context.get('request').user.profile.company
        company_profile_id_list = company.profiles.all().values_list('id', flat=True)
        for profile_id in value:
            if profile_id not in company_profile_id_list:
                raise serializers.ValidationError(f"Profile id {value} not found in user's company")
        return value


class DirectMailCampaignUpdateSerializer(DirectMailCampaignResponseSerializer):
    """
    Serializer to update DirectMailCampaign
    """
    campaign = CampaignSerializer(required=False)


class CampaignReturnSerializer(CampaignSerializer):
    """
    The docs don't pick up overriding `to_representation` on `CampaignSerializer`, which returns the
    expanded objects, so we're going to make this serializer to have the docs accurate.
    """
    market = MarketSerializer()
    created_by = SherpaUserSerializer()


class CampaignMinimumSerializer(serializers.ModelSerializer):
    """
    Give the minimum values needed for campaigns.

    Used in the unread messages for prospects as we need just a couple values from the campaign.
    """
    class Meta:
        model = Campaign
        fields = ('id', 'name', 'is_archived', 'is_direct_mail')


class CampaignIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignIssue
        fields = ('code', 'issue_desc', 'suggestions')


class ProspectSearchCampaignSerializer(serializers.ModelSerializer):
    """
    Serialized campaign for returning in the prospect search.
    """
    class Meta:
        model = Campaign
        fields = ('id', 'name', 'podio_push_email_address', 'zapier_webhook')


class CampaignBulkArchiveSerializer(serializers.Serializer):
    id_list = serializers.ListField(child=serializers.IntegerField())
    is_archived = serializers.BooleanField()


class CampaignNoteSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    created_by = SherpaUserSerializer(read_only=True)

    class Meta:
        model = CampaignNote
        fields = '__all__'
        read_only_fields = ('created_date',)


class CampaignStatsCampaignSerializer(serializers.ModelSerializer):
    """
    Serialize the campaign in the campaign stats.
    """
    class Meta:
        model = Campaign
        fields = ('id', 'name')


class CampaignStatsSerializer(serializers.ModelSerializer):
    """
    Show stats about individual campaigns at the company dashboard level.
    """
    campaign = CampaignStatsCampaignSerializer()
    performance_rating = serializers.DecimalField(max_digits=7, decimal_places=4)
    delivery_rate = serializers.IntegerField()
    response_rate = serializers.IntegerField()

    class Meta:
        model = CampaignDailyStats
        exclude = ('date',)


class CampaignFullStatsSerializer(serializers.ModelSerializer):
    """
    Serializer used to return full stats about the campaign including meta, message and import.

    This is shown at the campaign level, compared to the `CampaignStatsSerializer` which is used at
    the company level.
    """
    delivery_rate = serializers.SerializerMethodField()
    response_rate = serializers.SerializerMethodField()
    total_responses = serializers.SerializerMethodField()
    total_prospects = serializers.SerializerMethodField()
    total_sends_available = serializers.IntegerField(source='market.total_sends_available')
    daily_send_limit = serializers.IntegerField(source='market.total_initial_send_sms_daily_limit')
    total_leads = serializers.IntegerField(source='total_leads_generated')
    total_sms_sent_count = serializers.IntegerField(source='total_sent')
    total_skipped = serializers.IntegerField(source='campaign_stats.total_skipped')
    total_auto_dead_count = serializers.IntegerField(
        source='campaign_stats.total_auto_dead_count',
    )
    total_mobile = serializers.IntegerField(source='campaign_stats.total_mobile')
    total_landline = serializers.IntegerField(source='campaign_stats.total_landline')
    total_phone_other = serializers.IntegerField(source='campaign_stats.total_phone_other')
    total_wrong_number_count = serializers.IntegerField(
        source='campaign_stats.total_wrong_number_count',
    )

    def get_total_prospects(self, obj):
        # Total prospects should actulaly be looking at the total properties.
        return obj.total_properties

    def get_total_responses(self, obj):
        return obj.get_responses().count()

    def get_delivery_rate(self, obj):
        return obj.get_delivery_rate()

    def get_response_rate(self, obj):
        return obj.delivered_response_rate

    class Meta:
        model = Campaign
        fields = (
            'health', 'total_sms_sent_count', 'delivery_rate', 'response_rate', 'total_leads',
            'total_responses', 'total_prospects', 'daily_send_limit', 'total_sends_available',
            'total_skipped', 'total_initial_sms_undelivered', 'auto_dead_percentage',
            'total_auto_dead_count', 'phone_number_count', 'total_mobile', 'total_landline',
            'total_phone_other', 'total_litigators', 'total_internal_dnc',
            'total_wrong_number_count',
        )


class UploadProspectsSerializer(serializers.ModelSerializer):
    total_prospects = serializers.IntegerField(source='prospects_imported')
    total_properties = serializers.IntegerField(source='properties_imported')
    total_internal_dnc = serializers.IntegerField(source='total_internal_dnc2')
    total_litigator_list = serializers.IntegerField(source='total_litigators')
    new = serializers.SerializerMethodField()
    existing = serializers.SerializerMethodField()

    def get_new(self, obj):
        """
        Return count of new Prospects if direct to campaign upload. otherwise return Properties
        """
        if obj.campaign or not (obj.new_properties or obj.existing_properties):
            return obj.new
        return obj.new_properties

    def get_existing(self, obj):
        """
        Return count of existing Prospects if direct to campaign upload. otherwise return Properties
        """
        if obj.campaign or not (obj.new_properties or obj.existing_properties):
            return obj.existing
        return obj.existing_properties

    class Meta:
        model = UploadProspects
        fields = (
            "id",
            "campaign",
            "percent_complete",
            "last_row_processed",
            "status",
            "total_rows",
            "uploaded_filename",
            "upload_start",
            "upload_end",
            "upload_error",
            "total_properties",
            "total_prospects",
            "total_mobile_numbers",
            "total_litigator_list",
            "total_internal_dnc",
            "unique_property_tags",
            "new",
            "existing",
        )
        read_only_fields = (
            "total_properties",
            "total_prospects",
            "total_mobile_numbers",
            "total_litigator_list",
            "total_internal_dnc",
        )


class UploadProspectsResponseSerializer(serializers.ModelSerializer):
    """
    Response for mapping fields for `UploadProspect`. Used for documentation purposes.
    """
    confirm_additional_cost = serializers.BooleanField(default=False)
    cost = serializers.FloatField(default=0)

    class Meta:
        model = UploadProspects
        fields = (
            'id',
            'campaign',
            'confirm_additional_cost',
            'cost',
            'exceeds_count',
            'total_rows',
            'uploaded_filename',
        )


class UploadProspectsRequestSerializer(serializers.ModelSerializer):
    """
    Request for mapping fields for `UploadProspect`. Used for documentation purposes.
    """
    headers_matched = serializers.JSONField(required=True)
    valid_data = serializers.JSONField(required=True)
    confirm_additional_cost = serializers.BooleanField(default=False)

    class Meta:
        model = UploadProspects
        fields = (
            'id',
            'campaign',
            'confirm_additional_cost',
            'headers_matched',
            'total_rows',
            'uploaded_filename',
            'valid_data',
        )


class UploadProspectsStatusResponseSerializer(serializers.Serializer):
    """
    Response for checking upload prospect stuats.  Used for documentation purposes.
    """
    complete = serializers.BooleanField()

    class Meta:
        fields = ('complete',)


class FollowupCampaignSerializer(serializers.Serializer):
    """
    A series of filters to find eligible campaign prospects to add when creating a followup
    campaign.
    """
    campaign_name = serializers.CharField(required=True, max_length=255)
    responded = serializers.BooleanField(required=False)
    dnc = serializers.BooleanField(required=False)
    priority = serializers.BooleanField(required=False)
    qualified = serializers.BooleanField(required=False)
    wrong_number = serializers.BooleanField(required=False)
    verified = serializers.BooleanField(required=False)
    non_owner = serializers.BooleanField(required=False)
    skipped = serializers.BooleanField(required=False)
    skip_reason = serializers.CharField(required=False)
    retain_numbers = serializers.BooleanField(required=False, default=False)
    archive_original = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Allowing original follow-up campaign archive option during creation.',
    )
    lead_stage = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        help_text='An array of lead stage ids that corrospond to a companies lead stage numbers.',
    )
    message_search = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text='An array of strings that must be found in campaign prospect messages.',
    )

    def generate_note(self, company):  # noqa: C901
        """
        Builds a string of the filters during follow-up campaign creation.
        """
        note = ["Follow-up Filters"]

        note.append("Lead Stage")
        if self.validated_data.get("lead_stage", False):
            for pk in self.validated_data.get("lead_stage"):
                ls = LeadStage.objects.get(pk=pk, company=company)
                note.append(f"- {ls.lead_stage_title}")
        else:
            note.append("N/A")
        note.append("")

        note.append("Include prospects who have responded?")
        if self.validated_data.get("responded", None) is not None:
            if self.validated_data.get("responded"):
                note.append("Yes - only include the prospects that have replied")
            else:
                note.append("No - only include the prospects that haven't replied")

        else:
            # A none responded value corrosponds to ALL.
            note.append("All - include both prospects that have and haven't replied")
        note.append("")

        note.append("Prospects Who Are")
        entered = False
        if self.validated_data.get("priority", False):
            note.append("- Priority")
            entered = True
        if self.validated_data.get("qualified", False):
            note.append("- Qualified")
            entered = True
        if self.validated_data.get("verified", False):
            note.append("- Owner Verified")
            entered = True
        if self.validated_data.get("non_owner", False):
            note.append("- Non Owner")
            entered = True
        if not entered:
            note.append("N/A")
        note.append("")

        note.append("Skip Reason")
        if self.validated_data.get("skip_reason", False):
            reason = self.validated_data.get("skip_reason")
            if reason == CampaignProspect.SkipReason.CARRIER:
                note.append("Carrier Skip")
            elif reason == "threshold":
                note.append("5-day rule")
            else:
                note.append("Any")
        else:
            note.append("N/A")
        note.append("")

        note.append("Keywords")
        if self.validated_data.get("message_search", False):
            for keyword in self.validated_data.get("message_search"):
                note.append(f"- {keyword}")
        else:
            note.append("N/A")
        note.append("")

        note.append("Retain Initial Outgoing Numbers")
        if self.validated_data.get("retain_numbers"):
            note.append("Yes")
        else:
            note.append("No")
        note.append("")

        return "\n".join(note)


class ProspectTagByCampaignSerializer(serializers.Serializer):
    """
    Data that will be used to determine how many prospects should be updated along with what tags
    to add or remove.
    """
    add = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        help_text='Tag(s) to add to prospect(s).',
    )
    remove = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        help_text='Tag(s) to remove from prospect(s).',
    )

    def validate_add(self, tags):
        company = self.context.get('company')
        try:
            for pk in tags:
                PropertyTag.objects.get(pk=pk, company=company)
        except PropertyTag.DoesNotExist:
            raise serializers.ValidationError(f'Tag with id {pk} not found.')
        return tags

    def validate_remove(self, tags):
        company = self.context.get('company')
        try:
            for pk in tags:
                PropertyTag.objects.get(pk=pk, company=company)
        except PropertyTag.DoesNotExist:
            raise serializers.ValidationError(f'Tag with id {pk} not found.')
        return tags


class ModifyCampaignTagsSerializer(serializers.Serializer):
    tags = serializers.ListField(help_text="Array of campaign tag ids.")

    def validate_tags(self, value):
        """
        Ensure the tags belong to the company.
        """
        company = self.context.get('company')
        try:
            [company.campaigntag_set.get(pk=pk) for pk in value]
        except CampaignTag.DoesNotExist:
            raise serializers.ValidationError('Campaign tag not found.')
        return value


class YellowLetterSerializer(serializers.ModelSerializer):
    """
    Serialized campaign for returning in the prospect search.
    """
    FirstName = serializers.CharField(source='first_name')
    LastName = serializers.CharField(source='last_name')
    PropertyAddress = serializers.CharField(source='prop.address.address')
    PropertyCity = serializers.CharField(source='prop.address.city')
    PropertyState = serializers.CharField(source='prop.address.state')
    PropertyZip = serializers.CharField(source='prop.address.zip_code')
    MailingAddress = serializers.CharField(source='prop.mailing_address.address')
    Mailingcity = serializers.CharField(source='prop.mailing_address.city')
    MailingState = serializers.CharField(source='prop.mailing_address.state')
    Mailingzip = serializers.CharField(source='prop.mailing_address.zip_code')
    agent_name = serializers.SerializerMethodField()
    agent_number = serializers.SerializerMethodField()
    return_address_street = serializers.SerializerMethodField()
    return_address_zip = serializers.SerializerMethodField()
    full_name = serializers.CharField(default="")
    mailing_address2 = serializers.CharField(default="")

    def get_agent_name(self, obj):
        return self.context.get('agent_name')

    def get_agent_number(self, obj):
        return self.context.get('agent_number')

    def get_return_address_street(self, obj):
        return self.context.get('return_address_street')

    def get_return_address_zip(self, obj):
        return self.context.get('return_address_zip')

    class Meta:
        model = Prospect
        fields = (
            'FirstName',
            'LastName',
            'PropertyAddress',
            'PropertyCity',
            'PropertyState',
            'PropertyZip',
            'MailingAddress',
            'Mailingcity',
            'MailingState',
            'Mailingzip',
            'agent_name',
            'agent_number',
            'return_address_street',
            'return_address_zip',
            'full_name',
            'mailing_address2',
        )


class DirectMailTemplatesSerializer(serializers.Serializer):
    """
    Serializer to return valid Direct Mail templates.
    """
    id = serializers.CharField()
    name = serializers.CharField()


class YellowLetterTargetDateResponseSerializer(serializers.Serializer):
    """
    Serializer to return valid target date. Used for documentation.
    """
    success = serializers.BooleanField()
    answer = serializers.CharField()


class DirectMailCampaignSerializer(serializers.ModelSerializer):
    """
    Serializer to create DirectMailCampaign
    """
    campaign = DirectMailCreateCampaignSerializer()
    drop_date = serializers.DateField()
    creative_type = serializers.CharField(default="postcard")
    budget_per_order = serializers.DecimalField(
        decimal_places=2,
        max_digits=10,
        required=False,
    )
    note_for_processor = serializers.CharField(required=False)
    template = serializers.CharField()
    from_id = serializers.IntegerField()
    return_address = serializers.CharField()
    return_city = serializers.CharField()
    return_state = serializers.CharField()
    return_zip = serializers.CharField()
    return_phone = serializers.CharField()

    class Meta:
        model = DirectMailCampaign
        fields = (
            'id',
            'budget_per_order',
            'campaign',
            'creative_type',
            'drop_date',
            'note_for_processor',
            'template',
            'from_id',
            'return_address',
            'return_city',
            'return_state',
            'return_zip',
            'return_phone',
        )


class DirectMailCampaignStatsSerializer(serializers.ModelSerializer):
    """
    Show stats about individual campaigns at the company dashboard level.
    """
    get_delivery_rate = serializers.IntegerField()
    get_undeliverable_rate = serializers.IntegerField()
    tracking_url = serializers.CharField()

    class Meta:
        model = DirectMailCampaignStats
        fields = (
            'total_delivered_pieces',
            'total_undelivered_pieces',
            'get_delivery_rate',
            'get_undeliverable_rate',
            'tracking_url',
        )


class DMCampaignListProspectsSerializer(serializers.ModelSerializer):
    """
    Serializer to list the direct mail campaign prospects.
    """
    fullname = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    zip_code = serializers.CharField()
    campaign_count = serializers.IntegerField()
    property_tags_length = serializers.IntegerField()
    prospect_tags_length = serializers.IntegerField()
    property_tags = serializers.ListField(child=serializers.IntegerField())

    class Meta:
        model = Prospect
        fields = (
            'id',
            'fullname',
            'address',
            'city',
            'state',
            'zip_code',
            'phone_raw',
            'campaign_count',
            'do_not_call',
            'is_blocked',
            'is_priority',
            'is_qualified_lead',
            'wrong_number',
            'owner_verified_status',
            'property_tags_length',
            'property_tags',
            'prospect_tags_length',
        )


class RemoveDMCampaignRecipientsSerializer(serializers.Serializer):
    """
    Remove recipients from direct mail campaign.
    """
    action = serializers.ChoiceField(
        choices=['remove'],
        default='remove',
        help_text="Input action remove",
    )
    prospect_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False,
        help_text="Prospect IDs to removing from direct mail campaign.",
    )


class RetrieveDirectMailEventDatesSerializer(serializers.ModelSerializer):
    """
    Fetch Campaign specific event dates.
    """
    campaign_id = serializers.SerializerMethodField()

    class Meta:
        model = DirectMailOrder
        fields = (
            'campaign_id',
            'received_by_print_date',
            'in_production_date',
            'in_transit_date',
            'processed_for_delivery_date',
            'delivered_date',
            'scheduled_date',
            'drop_date',
            'tracking_url',
        )

    def get_campaign_id(self, obj):
        return self.context.get('campaign_pk')
