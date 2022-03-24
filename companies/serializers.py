from django.conf import settings
from django.db import IntegrityError
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.serializers import UserProfileSerializer
from billing.models import product
from campaigns.utils import get_dm_charges
from sherpa.models import (
    Company,
    Features,
    InvitationCode,
    LeadStage,
    SubscriptionCancellationRequest,
)
from sherpa.serializers import InvitationCodeSerializer
from sms.serializers import AlternateMessageValidationMixin, SMSTemplateCategorySerializer
from .models import (
    CompanyGoal,
    CompanyPodioCrm,
    CompanyPropStackFilterSettings,
    DownloadHistory,
    TelephonyConnection,
)


class CompanySerializer(AlternateMessageValidationMixin, serializers.ModelSerializer):
    invitation_code = InvitationCodeSerializer()
    profiles = UserProfileSerializer(many=True)
    sms_sent_today = serializers.IntegerField(
        source='total_intial_sms_sent_today_count', read_only=True)
    has_taken_discount = serializers.BooleanField(
        source='cancellation_discount', read_only=True)
    template_categories = SMSTemplateCategorySerializer(many=True)
    postcard_price = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            'id',
            'name',
            'profiles',
            'timezone',
            'billing_address',
            'city',
            'state',
            'zip_code',
            'subscription_status',
            'auto_dead_enabled',
            'is_messaging_disabled',
            'total_skip_trace_savings',
            'monthly_upload_limit',
            'sherpa_balance',
            'skip_trace_price',
            'cost_per_upload',
            'braintree_id',
            'subscription_id',
            'total_initial_messages_sent_today',
            'total_initial_send_sms_daily_limit',
            'is_billing_exempt',
            'default_alternate_message',
            'start_time',
            'end_time',
            'send_carrier_approved_templates',
            'outgoing_company_names',
            'outgoing_user_names',
            'use_sender_name',
            'sms_sent_today',
            'invitation_code',
            'auto_verify_prospects',
            'default_zapier_webhook',
            'record_calls',
            'has_cancellation_request_pending',
            'has_taken_discount',
            'template_categories',
            'auto_filter_messages',
            'has_company_specified_telephony_integration',
            'auto_filter_messages',
            'enable_twilio_integration',
            'telephony_connections',
            'enable_optional_opt_out',
            'allow_telnyx_add_on',
            'postcard_price',
        )
        read_only_fields = (
            'cost_per_upload',
            'subscription_status',
            'total_skip_trace_savings',
            'sherpa_balance',
            'braintree_id',
            'subscription_id',
            'is_billing_exempt',
            'total_initial_messages_sent_today',
            'sms_sent_today',
            'has_cancellation_request_pending',
            'has_taken_discount',
            'enable_twilio_integration',
            'telephony_connections',
            'has_company_specified_telephony_integration',
            'allow_telnyx_add_on',
            'postcard_price',
        )

    def validate_default_alternate_message(self, value):
        """
        Handling of the default alternate message has the same validation as the SMS alternate
        message from `AlternateMessageValidationMixin`, however the field here is named differently.
        """
        return self.validate_alternate_message(value)

    def validate_default_zapier_webhook(self, value):
        """
        Validate the Zapier webhook is part of the company.  Can be set to null.
        """
        if value and self.context['request'].user.profile.company_id != value.company_id:
            raise ValidationError('Could not locate the zapier webhook.')
        return value

    def validate(self, data):
        use_carrier_approved = data.get(
            'send_carrier_approved_templates', self.instance.send_carrier_approved_templates)
        use_sender_name = data.get('use_sender_name', self.instance.use_sender_name)
        company_names = data.get('outgoing_company_names', self.instance.outgoing_company_names)
        user_names = data.get('outgoing_user_names', self.instance.outgoing_user_names)

        names_set = company_names and (user_names or use_sender_name)
        if use_carrier_approved and not names_set:
            raise ValidationError(
                {
                    "send_carrier_approved_templates": [
                        ("Must set outgoing first name or choose to use sending user's first name, "
                         "and at least one outgoing company name is required "),
                    ],
                },
            )

        return data

    def get_postcard_price(self, obj):
        return get_dm_charges(company=obj)


class CompanySlowSerializer(serializers.ModelSerializer):
    """
    Data on the company object that takes too long to return from the me endpoint and should be
    fetched separately to keep load times acceptable.
    """
    class Meta:
        model = Company
        fields = (
            'upload_count_remaining_current_billing_month',
        )


class CompanyRegisterSerializer(serializers.ModelSerializer):
    name = serializers.CharField(required=True)
    real_estate_experience_rating = serializers.ChoiceField(
        choices=Company.RealEstateExperience.CHOICES,
        required=True,
    )
    how_did_you_hear = serializers.CharField(required=False)
    interesting_features = serializers.MultipleChoiceField(
        choices=[x[0] for x in Features.CHOICES],
        required=False,
    )
    invitation_code = serializers.CharField(required=False)

    class Meta:
        model = Company
        fields = (
            'id',
            'name',
            'real_estate_experience_rating',
            'how_did_you_hear',
            'interesting_features',
            'invitation_code',
            'timezone',
            'billing_address',
            'city',
            'state',
            'zip_code',
        )
        read_only_fields = ('id',)

    def validate_invitation_code(self, value):
        """
        Validates the invitation code.  If it's valid, it switches the value to the actual
        instance of InvitationCode.
        """
        try:
            value = InvitationCode.objects.get(is_active=True, code=value)
        except InvitationCode.DoesNotExist:
            raise ValidationError('The invitation code does not exist.')
        return value


class CompanyGoalSerializer(serializers.ModelSerializer):

    class Meta:
        model = CompanyGoal
        fields = (
            'id',
            'company',
            'start_date',
            'end_date',
            'budget',
            'leads',
            'avg_response_time',
            'new_campaigns',
            'delivery_rate_percent',
            'created_at',
        )


class LeadStageSerializer(serializers.ModelSerializer):

    class Meta:
        model = LeadStage
        fields = (
            'id',
            'company',
            'lead_stage_title',
            'is_active',
            'is_custom',
            'description',
            'sort_order',
        )
        read_only_fields = ('is_custom',)


class CompanyCampaignStatsSerializer(serializers.Serializer):
    """
    Serialize the data to be displayed for a company's campaign stats on their dashboard.
    """
    active_campaign_count = serializers.IntegerField()
    new_lead_count = serializers.IntegerField()
    total_sms_sent_count = serializers.IntegerField()
    response_rate = serializers.IntegerField()
    delivery_rate = serializers.IntegerField()


class PurchaseSherpaCreditsSerializer(serializers.Serializer):
    """
    Used just for documentation to purchase sherpa credits.
    """
    amount = serializers.FloatField()

    class Meta:
        fields = ('amount', )


class CompanyProfileStatsSerializer(serializers.Serializer):
    """
    Display the stats for profiles in a company.
    """
    id = serializers.IntegerField()
    name = serializers.CharField()
    attempts = serializers.IntegerField()
    delivered = serializers.IntegerField()
    leads_created = serializers.IntegerField()
    lead_rate = serializers.IntegerField()
    avg_response_time = serializers.IntegerField()


class CompanyPaymentMethodGetSerializer(serializers.Serializer):
    payment_method_nonce = serializers.CharField(required=False)


class CompanyPaymentMethodSerializer(serializers.Serializer):
    payment_method_nonce = serializers.CharField()


class SubscriptionRequestSerializer(serializers.Serializer):
    """
    Data that is expected to create or update a subscription.
    """
    plan_choices = [product.SMS_STARTER, product.SMS_CORE, product.SMS_PRO]
    plan_id = serializers.ChoiceField(choices=plan_choices)
    annual = serializers.BooleanField()


class DownloadHistorySerializer(serializers.ModelSerializer):
    """
    List of all downloads that have been generated for a company by a user.
    """
    created_by = serializers.SerializerMethodField()

    def get_created_by(self, obj):
        return obj.created_by.get_full_name()

    class Meta:
        model = DownloadHistory
        fields = ('status', 'file', 'download_type', 'filters', 'created_by', 'created', 'is_bulk')


class FileDownloadPollingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DownloadHistory
        fields = ('status', 'file', 'download_type', 'percentage')


class DNCSerializer(serializers.Serializer):
    """
    All phones that have been marked DNC within a company.

    TODO Should phone be a list?
    """
    phone = serializers.CharField(read_only=True, source='phone_raw')


class DNCExportSerializer(serializers.Serializer):
    """
    Used to return data to the frontend when exporting DNC data.
    """
    id = serializers.UUIDField(required=True)
    message = serializers.CharField()


class DNCBulkRemoveSerializer(serializers.Serializer):
    """
    Used to return data when removing bulk phone numbers from a company's DNC list.
    """
    has_error = serializers.BooleanField()
    detail = serializers.CharField()


class SetInvitationCodeSerializer(serializers.Serializer):
    """
    Serializer to handle the expected payload for setting a company's invitation code.
    """
    code = serializers.CharField(
        required=True,
        help_text="The invitation code to attach to the company.",
    )


class ProspectCountSerializer(serializers.Serializer):
    """
    Data to return when getting a company's prospect count.
    """
    count = serializers.IntegerField(required=True)


class SubscriptionCancellationRequestSerializer(serializers.ModelSerializer):
    """
    Data that is used to handle a companys cancellation request.
    """
    class Meta:
        model = SubscriptionCancellationRequest
        fields = (
            'discount',
            'pause',
            'new_plan',
            'cancellation_reason',
            'cancellation_reason_text',
        )


class SubscriptionCancellationResponseSerializer(serializers.Serializer):
    """
    Response data to send back to a cancellation request.
    """
    discount_applied = serializers.BooleanField(
        read_only=True,
        help_text="Explains if the discount was applied during the cancellation flow.",
    )
    last_billing_date = serializers.DateField(
        read_only=True, help_text="Date when the last billing cycle occurs.")
    subscription_price = serializers.FloatField(
        read_only=True, help_text="New pricing amount for paused or downgraded accounts.")


class TelephonyConnectionSerializer(serializers.ModelSerializer):
    """
    Data that is set a company's Telephony Integration.
    """
    class Meta:
        model = TelephonyConnection
        fields = (
            'api_key',
            'api_secret',
            'provider',
        )


class TelephonySyncSerializer(serializers.Serializer):
    """
    Used just for documentation to sync TelephonyConnection.
    """
    id = serializers.IntegerField()
    provider = serializers.CharField()

    class Meta:
        fields = ('id', 'provider')


class TemplateListSerializer(serializers.Serializer):
    """
    List of carrier-approve template ids.
    """
    templates = serializers.ListField(child=serializers.IntegerField())

    def validate_templates(self, templates):
        required_size = 2 if settings.TEST_MODE else 30
        if len(templates) < required_size:
            raise ValidationError('Must select a minimum of 30 templates.')
        return templates


class CompanyPodioIntegrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyPodioCrm
        fields = (
            "organization",
            "workspace",
            "application",
            "access_token",
            "refresh_token",
            "expires_in_token",
        )


class CompanyPropStackFilterSettingsSerializer(serializers.ModelSerializer):
    """
    Serializer for property stacker filter Settings.
    """

    class Meta:
        model = CompanyPropStackFilterSettings
        fields = ("id", "filter_name", "filter_json")

    def create(self, validated_data):
        try:
            request = self.context.get("request")
            return CompanyPropStackFilterSettings.objects.create(
                company=request.user.profile.company,
                created_by=request.user,
                **validated_data,
            )
        except IntegrityError:
            raise ValidationError(
                {
                    "filter_name": "Filter name already exists. Please choose another name",
                },
            )
