from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.serializers import SherpaUserSerializer
from sherpa.models import SMSMessage, SMSPrefillText, SMSTemplate
from sherpa.utils import has_link
from . import VALID_TAGS
from .models import CarrierApprovedTemplate, SMSTemplateCategory
from .utils import find_banned_words, find_spam_words, get_tags


class SMSMessageSerializer(serializers.ModelSerializer):

    class Meta:
        model = SMSMessage
        fields = (
            'id',
            'prospect',
            'message',
            'media_url',
            'from_number',
            'dt',
            'from_prospect',
            'unread_by_recipient',
            'from_name',
        )
        read_only_fields = ('id', 'prospect', 'message', 'from_number', 'dt', 'from_prospect')


class SMSMessageCondensedSerializer(serializers.ModelSerializer):
    """
    Limit fields to be displayed for just showing the display message of a prospect.
    """
    class Meta:
        model = SMSMessage
        fields = ('id', 'message', 'dt', 'from_prospect')


class PublicConversationSerializer(serializers.ModelSerializer):
    """
    Data shown for the conversation when getting prospect conversation by their token.
    """
    class Meta:
        model = SMSMessage
        fields = ('id', 'message', 'dt', 'from_prospect', 'from_name', 'from_number')


class BaseMessageValidationMixin:
    """
    Shared logic for both alternate_message and message.
    """
    def _validate_url(self, value):
        contains_url = has_link(value)
        if contains_url:
            raise ValidationError(f"Message can't contain URL links. ({contains_url})")

    def _validate_tag_format(self, value, ignored_tags=None):
        """
        Validate that all tags are completed and all tags are valid.
        """
        if value.count('{') != value.count('}'):
            raise ValidationError("Message contains incorrectly formed merge tags.")

        tags = list(set(get_tags(value)) ^ set(ignored_tags or []))
        for tag in tags:
            if tag not in VALID_TAGS:
                raise ValidationError(f'Invalid tag "{tag}" found in message text.')

    def _validate_banned_words(self, value):
        banned_words = find_banned_words(value)
        if banned_words:
            raise ValidationError(
                f'Message may not contain banned words "{", ".join(banned_words)}".')

    def _validate_spam_words(self, value):
        spam_words = find_spam_words(value)
        if spam_words:
            raise ValidationError(
                f'Message may not contain spam words "{", ".join(spam_words)}".')

    def _validate_required_tags(self, value):
        """
        Check that all the required tags are in the message.
        """
        missing_tags = []
        tags = get_tags(value)
        if 'CompanyName' not in tags:
            missing_tags.append('{CompanyName}')

        if missing_tags:
            is_plural = 's' if len(missing_tags) > 1 else ''
            raise ValidationError(f'Must contain required tag{is_plural} {", ".join(missing_tags)}')


class AlternateMessageValidationMixin(BaseMessageValidationMixin):
    """
    Validate that the alternate message does not have improper tags, links or banned words and has
    the required tags.
    """
    def validate_alternate_message(self, value):
        self._validate_required_tags(value)
        self._validate_url(value)

        self._validate_tag_format(value, ignored_tags=['CompanyName'])
        self._validate_banned_words(value)
        self._validate_spam_words(value)

        return value


class MessageValidationMixin(BaseMessageValidationMixin):
    def validate_message(self, value):
        self._validate_url(value)
        self._validate_tag_format(value)
        self._validate_banned_words(value)
        return value


class SMSTemplateSerializer(
        AlternateMessageValidationMixin,
        MessageValidationMixin,
        serializers.ModelSerializer):
    alternate_message = serializers.CharField(required=True)
    message = serializers.CharField(required=True)
    created_by = SherpaUserSerializer(read_only=True)
    category = serializers.PrimaryKeyRelatedField(
        required=True,
        queryset=SMSTemplateCategory.objects.all(),
    )

    class Meta:
        model = SMSTemplate
        fields = (
            'id',
            'company',
            'category',
            'message',
            'is_active',
            'template_name',
            'alternate_message',
            'created',
            'created_by',
            'last_updated',
            'is_invalid',  # DEPRECATED: use `is_valid` instead.
            'is_valid',
            'sort_order',
            'delivery_percent',
            'response_rate',
        )
        read_only_fields = (
            'id',
            'is_invalid',
            'is_valid',
            'company',
            'delivery_percent',
            'response_rate',
        )

    def validate_message(self, value):
        """
        Extra validation of message specific to the `SMSTemplate` that does not get applied to
        `SMSPrefillText`, mainly checks for the required tags which are not required in quick
        replies.
        """
        super(SMSTemplateSerializer, self).validate_message(value)
        self._validate_spam_words(value)
        self._validate_required_tags(value)
        return value


class QuickReplySerializer(MessageValidationMixin, serializers.ModelSerializer):
    class Meta:
        model = SMSPrefillText
        fields = (
            'id',
            'question',
            'message',
            'message_formatted',
            'is_invalid',
            'sort_order',
            'company',
        )
        read_only_fields = ('id', 'company', 'message_formatted', 'is_invalid', 'sort_order')


class QuickReplyDetailSerializer(MessageValidationMixin, serializers.ModelSerializer):
    class Meta:
        model = SMSPrefillText
        fields = ('id', 'question', 'message', 'message_formatted', 'sort_order', 'company')
        read_only_fields = ('id', 'company', 'message_formatted')


class CarrierApprovedTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarrierApprovedTemplate
        fields = ('id', 'message', 'alternate_message')
        read_only_fields = ('message', 'alternate_message')


class SMSTemplateCategorySerializer(serializers.ModelSerializer):
    is_custom = serializers.BooleanField(read_only=True)
    templates = serializers.ListField(child=serializers.IntegerField(), required=False)

    class Meta:
        model = SMSTemplateCategory
        fields = ('id', 'title', 'is_custom', 'templates')


class SMSTemplateCategorySortSerializer(serializers.Serializer):
    template = serializers.IntegerField(min_value=1)
    order = serializers.IntegerField(min_value=1)

    def validate_template(self, value):
        if not SMSTemplate.objects.filter(id=value, company=self.context.get('company')).exists():
            raise serializers.ValidationError('Template does not exist.')
        return value

    def validate_order(self, value):
        if value > self.context.get('category').max_order:
            raise serializers.ValidationError('Order set too high.')
        return value
