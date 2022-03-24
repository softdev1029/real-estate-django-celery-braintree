from rest_framework import serializers

from .models import Address, Property, PropertyTag


class PropertyTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyTag
        exclude = ('company',)


class AddressSerializer(serializers.ModelSerializer):
    """
    Returned address data.
    """
    class Meta:
        model = Address
        fields = ('id', 'address', 'city', 'state', 'zip_code')


class PropertySerializer(serializers.ModelSerializer):
    """
    Returned property data.
    """
    tags = PropertyTagSerializer(many=True)
    address = AddressSerializer()
    mailing_address = AddressSerializer(required=False)

    class Meta:
        model = Property
        exclude = ('company', 'created')
