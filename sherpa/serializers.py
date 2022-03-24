from ast import literal_eval

from rest_framework import serializers

from .models import InvitationCode, SupportLink, ZapierWebhook


class SupportLinkSerializer(serializers.ModelSerializer):

    icon = serializers.SerializerMethodField()

    def get_icon(self, obj):
        """
        Return the icon as an array instead of string.
        """
        if not obj.icon:
            return []
        return literal_eval(obj.icon)

    class Meta:
        model = SupportLink
        fields = '__all__'


class ZapierWebhookSerializer(serializers.ModelSerializer):
    is_default = serializers.BooleanField(read_only=True)

    class Meta:
        model = ZapierWebhook
        fields = ('id', 'webhook_url', 'name', 'status', 'is_default')


class IntegerListSerializer(serializers.Serializer):
    """
    A very simple serializer that takes in a list of integers.  Maybe too simple.
    """
    values = serializers.ListField(child=serializers.IntegerField())


class InvitationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvitationCode
        fields = ('id', 'code', 'is_skip_trace_invitation', 'allow_starter')


class InvitationCodeWithBraintreeSerializer(serializers.ModelSerializer):
    """
    Add extra data from braintree to the invitation code.
    """
    class Meta:
        model = InvitationCode
        fields = ('id', 'code', 'is_skip_trace_invitation', 'allow_starter', 'discount_amount')


class EmptySerializer(serializers.Serializer):
    """
    Show a response object that does not have any data, used for documentaiton.
    """
    pass
