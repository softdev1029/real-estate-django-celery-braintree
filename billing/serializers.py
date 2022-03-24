from rest_framework import serializers

from .models import Plan


class BraintreeTransactionSerializer(serializers.Serializer):
    """
    Serialize a transaction that comes from braintree.
    """
    id = serializers.CharField()
    datetime = serializers.DateTimeField()
    last_4 = serializers.CharField()
    amount = serializers.DecimalField(max_digits=7, decimal_places=2)
    status = serializers.CharField()
    type = serializers.CharField(required=False)


class SubscriptionModifierSerializer(serializers.Serializer):
    """
    Serialize data about a braintree subscription addon or discount.
    """
    total = serializers.SerializerMethodField()
    amount = serializers.DecimalField(max_digits=7, decimal_places=2)
    name = serializers.CharField()
    quantity = serializers.IntegerField()

    def get_total(self, obj):
        return "{:.2f}".format(obj.amount * obj.quantity)


class BraintreeSubscriptionSerializer(serializers.Serializer):
    """
    Data points about a company's braintree subscription
    """
    price = serializers.DecimalField(max_digits=7, decimal_places=2)
    next_bill_amount = serializers.DecimalField(max_digits=7, decimal_places=2)
    next_billing_date = serializers.CharField()
    plan_id = serializers.CharField()

    discounts = SubscriptionModifierSerializer(many=True)
    add_ons = SubscriptionModifierSerializer(many=True)
    is_cancellable = serializers.BooleanField(default=False)
    is_annual = serializers.BooleanField()


class BraintreeCreditCardSerializer(serializers.Serializer):
    """
    Data used from the braintree credit card object.

    https://developers.braintreepayments.com/reference/response/credit-card/python
    """
    expired = serializers.BooleanField()
    last_4 = serializers.CharField()
    masked_number = serializers.CharField()


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        exclude = ('is_public', )
