from rest_flex_fields.serializers import FlexFieldsSerializerMixin

from django.db.models import Q
from rest_framework import serializers

from accounts.serializers import SherpaUserSerializer, UserProfileSerializer
from campaigns.serializers import CampaignMinimumSerializer, ProspectSearchCampaignSerializer
from core.utils import clean_phone
from sherpa.models import Activity, Campaign, CampaignProspect, Note, Prospect, UserProfile
from sherpa.serializers import IntegerListSerializer
from sms.models import SMSTemplateCategory
from sms.serializers import PublicConversationSerializer, SMSMessageCondensedSerializer
from sms.utils import fetch_phonenumber_info, find_banned_words
from .models import ProspectRelay, ProspectTag


class ProspectActivitySerializer(serializers.ModelSerializer):
    """
    Display data about a prospect's activity.
    """
    date = serializers.DateTimeField(source='date_utc', read_only=True)

    class Meta:
        model = Activity
        fields = ('id', 'date', 'title', 'description')


class ProspectRelayProspectSerializer(serializers.ModelSerializer):
    """
    Data to show for a prospect, when being shown on a prospect relay.
    """
    fullname = serializers.CharField(source='get_full_name')

    class Meta:
        model = Prospect
        fields = (
            'id',
            'fullname',
            'phone_display',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'address_display',  # Deprecated 20200430
        )


class ProspectRelaySerializer(serializers.ModelSerializer):
    """
    Display the data representation of a prospect relay connection.
    """
    agent_profile = UserProfileSerializer(read_only=True)
    prospect = ProspectRelayProspectSerializer(read_only=True)

    class Meta:
        model = ProspectRelay
        fields = ('id', 'agent_profile', 'prospect', 'created', 'last_activity')


class ProspectSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    display_message = SMSMessageCondensedSerializer(read_only=True)
    relay = ProspectRelaySerializer(read_only=True)
    sherpa_phone_number = serializers.SerializerMethodField()
    opted_out = serializers.BooleanField(allow_null=True, default=False, read_only=True)
    phone_formatted_display = serializers.CharField(source='phone_formatted_display_calculated')
    activities = ProspectActivitySerializer(required=False, many=True, read_only=True)
    relay_blocked = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    property_id = serializers.SerializerMethodField()

    def get_sherpa_phone_number(self, obj):
        return obj.sherpa_phone_number_obj.phone if obj.sherpa_phone_number_obj else None

    def get_property_id(self, obj):
        if not obj.prop:
            return None

        return obj.prop.id

    class Meta:
        model = Prospect
        fields = (
            'id',
            'first_name',
            'last_name',
            'name',
            'phone_display',
            'phone_raw',
            'phone_formatted_display',
            'phone_type',
            'property_id',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'address_display',
            'has_unread_sms',
            'reminder_date_local',
            'reminder_date_utc',
            'reminder_agent',
            'display_message',
            'is_priority',
            'is_qualified_lead',
            'sherpa_phone_number',
            'do_not_call',
            'opted_out',
            'owner_verified_status',
            'wrong_number',
            'lead_stage',
            'agent',
            'emailed_to_podio',
            'pushed_to_zapier',
            'zillow_link',
            'tags',
            'total_view_link',
            'message_disable_reason',
            'token',
            'relay',
            'street_view_url',
            'is_blocked',
            'activities',
            'relay_blocked',
        )

    expandable_fields = {
        'campaign_prospects': ('prospects.serializers.CampaignProspectSerializer', {
            'source': 'campaignprospect_set.all',
            'many': True,
        }),
        'campaigns': ('campaigns.serializers.CampaignSerializer', {
            'source': 'campaign_qs',
            'many': True,
        }),
        'agent': ('accounts.serializers.UserProfileSerializer', {}),
        'messages': ('sms.serializers.SMSMessageSerializer', {
            'many': True,
            'source': 'messages',
        }),
    }

    def get_tags(self, obj):
        if not obj.prop:
            return []
        return list(obj.prop.tags.values_list('id', flat=True))

    def get_relay_blocked(self, obj):
        return obj.is_in_twilio_market


class ProspectSearchSerializer(serializers.ModelSerializer):
    campaigns = ProspectSearchCampaignSerializer(many=True, source='campaign_qs')
    sherpa_phone_number = serializers.SerializerMethodField()

    def get_sherpa_phone_number(self, obj):
        return obj.sherpa_phone_number_obj.phone if obj.sherpa_phone_number_obj else None

    class Meta:
        model = Prospect
        fields = (
            'id',
            'first_name',
            'last_name',
            'name',
            'phone_display',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'lead_stage',
            'agent',
            'do_not_call',
            'emailed_to_podio',
            'is_priority',
            'is_qualified_lead',
            'owner_verified_status',
            'reminder_date_local',
            'reminder_agent',
            'pushed_to_zapier',
            'sherpa_phone_number',
            'zillow_link',
            'campaigns',
            'token',
            'tags',
            'is_blocked',
        )


class ProspectSendMessageSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)

    def validate_message(self, value):
        banned_words = find_banned_words(value)
        if banned_words:
            raise serializers.ValidationError(
                f'Message contains banned words: {",".join(banned_words)}')
        return value


class ProspectNoteSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    created_by = SherpaUserSerializer(read_only=True)

    class Meta:
        model = Note
        fields = '__all__'
        read_only_fields = ('created_date',)


class CampaignProspectSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    prospect = ProspectSerializer(read_only=True, expand=['messages'])
    campaign = CampaignMinimumSerializer(read_only=True)
    sms_msg_text = serializers.SerializerMethodField()

    class Meta:
        model = CampaignProspect
        fields = (
            'id',
            'sms_msg_text',
            'campaign',
            'prospect',
            'sms_status',
            'absolute_url',
            'is_priority',
            'has_unread_sms',
            'unread_user_id_array',
            'last_updated',
            'has_been_viewed',
        )
        read_only_fields = (
            'last_updated',
        )

    expandable_fields = {
        'campaign': ('campaigns.serializers.CampaignSerializer', {}),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category = None
        if self.context.get('category_id'):
            self.category = SMSTemplateCategory.objects.get(id=self.context.get('category_id'))
        self.current_template = None

    def get_template(self, obj):
        if self.current_template:
            return self.current_template.id
        return None

    def get_sms_msg_text(self, obj):
        """
        Add sender name so it displays correctly in preview in case 'use_sender_name' enabled.
        """
        if self.current_template is None:
            if self.category:
                self.current_template = self.category.first_template
            else:
                if obj.campaign.sms_template:
                    self.current_template = obj.campaign.sms_template
                else:
                    cats = obj.campaign.company.template_categories
                    self.current_template = cats.filter(
                        Q(smstemplate__isnull=False) & Q(smstemplate__is_active=True),
                    ).first().first_template
        else:
            self.current_template = self.current_template.category.next_template(
                self.current_template,
            ) if self.current_template.category else self.current_template
        request = self.context.get("request")
        data = {
            'msg': '',
            'template': self.current_template.id,
        }
        if not request:
            data['msg'] = obj.sms_msg_text(template=self.current_template)
        else:
            data['msg'] = obj.sms_msg_text(request.user.first_name, template=self.current_template)

        return data


class CampaignProspectUnreadSerializer(FlexFieldsSerializerMixin, serializers.ModelSerializer):
    """
    Data to serializer for getting unread campaign prospects.
    """
    prospect = ProspectSerializer(read_only=True, expand=['messages'])
    campaign = CampaignMinimumSerializer(read_only=True)

    class Meta:
        model = CampaignProspect
        fields = (
            'id',
            'campaign',
            'prospect',
            'sms_status',
            'absolute_url',
            'is_priority',
            'has_unread_sms',
            'unread_user_id_array',
            'last_updated',
            'has_been_viewed',
        )
        read_only_fields = (
            'last_updated',
        )

    expandable_fields = {
        'campaign': ('campaigns.serializers.CampaignSerializer', {}),
    }


class ProspectCRMActionSerializer(serializers.ModelSerializer):
    """
    Used just for documentation to show the required payload for sending CRM actions.
    """

    class Meta:
        model = CampaignProspect
        fields = ['campaign']


class PublicProspectSerializer(serializers.ModelSerializer):
    """
    Used to display the data for the public prospect page.
    """
    messages = PublicConversationSerializer(many=True, source='get_messages')
    campaign_name = serializers.SerializerMethodField()

    def get_campaign_name(self, obj):
        first_campaign = obj.campaign_qs.first()
        return first_campaign.name if first_campaign else ''

    class Meta:
        model = Prospect
        fields = ['address_display', 'zillow_link', 'name', 'messages', 'campaign_name']


class CloneProspectSerializer(serializers.ModelSerializer):
    """
    Expected data to receive for cloning a prospect.
    """
    campaign = serializers.PrimaryKeyRelatedField(
        required=True,
        help_text="Campaign id that we're wanting to clone prospect into.",
        queryset=Campaign.objects.all(),
    )
    phone_raw = serializers.CharField(
        required=True,
        help_text="Valid mobile phone that doesn't already exist in company's prospects.",
    )

    class Meta:
        model = Prospect
        fields = (
            'campaign',
            'first_name',
            'last_name',
            'property_address',
            'property_city',
            'property_state',
            'property_zip',
            'phone_raw',
        )

    def validate(self, data):
        """
        Extra validation around the cloned prospect's phone raw.
        """
        # Check if the prospect phone number already exists for company. If we get the data clean
        # and can use unique_together, this can be removed.
        phone_raw = clean_phone(data['phone_raw'])
        company = self.context.get('company')
        if company.prospect_set.filter(phone_raw=phone_raw).exists():
            raise serializers.ValidationError({
                'phone_raw': 'Phone number already exists for company.',
            })

        # Check that the phone type is mobile. Use the default since lookup is always Telnyx.
        carrier = fetch_phonenumber_info(phone_raw)
        if carrier['type'] != 'mobile':
            raise serializers.ValidationError({'phone_raw': 'Phone number is not a mobile number.'})

        return data

    def validate_phone_raw(self, value):
        """
        Check that the phone number is valid.
        """
        if not clean_phone(value):
            raise serializers.ValidationError('Invalid phone number')
        return value


class ProspectRelayConnectSerializer(serializers.ModelSerializer):
    """
    Serializer for connecting a prospect to an agent relay.
    """
    class Meta:
        model = ProspectRelay
        fields = ('agent_profile', 'prospect')


class ProspectTagSerializer(serializers.ModelSerializer):
    """
    Get Prospect tags.
    """
    class Meta:
        model = ProspectTag
        fields = ('id', 'name', 'company', 'created', 'prospect_count', 'is_custom', 'order')

        validators = [
            serializers.UniqueTogetherValidator(
                queryset=model.objects.all(),
                fields=('company', 'name'),
                message="Tag must be unique.",
            ),
        ]


class ProspectPushToCampaignSerializer(serializers.Serializer):
    """
    Push Prospect to Campaign Serializer.
    """
    campaign = serializers.IntegerField(required=True)
    tags = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=True,
        required=False,
        help_text='Tag(s) to add to prospect(s).',
    )

    def validate_add(self, tags):
        company = self.context.get('company')
        try:
            for pk in tags:
                ProspectTag.objects.get(pk=pk, company=company)
        except ProspectTag.DoesNotExist:
            raise serializers.ValidationError(f'Tag with id {pk} not found.')
        return tags


class CampaignProspectBulkActionSerializer(IntegerListSerializer):
    """
    Expected data to be received for performing bulk actions.
    """
    action = serializers.ChoiceField(choices=CampaignProspect.BulkToggleActions.CHOICES)


class BulkActionResponseSerializer(serializers.Serializer):
    """
    Serialized data that is returned in response for bulk actions.
    """
    rows_updated = serializers.IntegerField()


class UnreadMessagesSerializer(serializers.Serializer):
    """
    Data returned to show the unread messages and count specific to unique unread messages.
    """
    count = serializers.IntegerField()
    results = CampaignProspectUnreadSerializer(many=True)


class AssignNumberSerializer(serializers.Serializer):
    """
    Data that could be used when assigning a sherpa number to a prospect.
    """
    force_assign = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Force a reassignment in the event the prospect already has a number assigned.",
    )
    campaign_id = serializers.IntegerField(
        required=False,
        help_text="Used to locate the prospects campaignprospect instance.  If not supplied,\
                   the system will choose the first found campaign the prospect is in.",
    )


class BatchSendRequestSerializer(serializers.Serializer):
    """
    Request data that is accepted by the batch send action.
    """
    action = serializers.ChoiceField(
        required=False,
        choices=['dnc', 'skip'],
        help_text='Extra action to send with the batch send request.',
    )
    template = serializers.IntegerField(
        required=False,
        help_text='SMS Template to use during send.  If not provided, will default to campaign.',
    )


class ProspectReminderSerializer(serializers.Serializer):
    """
    Data to set on prospect reminder.
    """
    time = serializers.DateTimeField(help_text='The date and time when to remind the agent.')
    agent = serializers.IntegerField(help_text='The agent profile ID.')

    def validate_agent(self, agent):
        company = self.context.get('company')
        if not UserProfile.objects.filter(id=agent, company=company).exists():
            raise serializers.ValidationError('Agent does not exist.')
        return agent
