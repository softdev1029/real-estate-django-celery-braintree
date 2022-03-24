from rest_framework import serializers

from phone.models.provider import Provider


class BrandSerializer(serializers.ModelSerializer):
    """
    Brand request to create a brand in TCR
    """

    class Meta:
        model = Provider
        fields = [
            'id',
        ]


class BrandTransferSerializer(serializers.Serializer):
    """
    Brand transfer for an existing brand in TCR
    """

    brand_id = serializers.CharField()
    email_address = serializers.EmailField()
    phone_number = serializers.CharField()

    def validate_brand_id(self, brand_id):
        if not len(brand_id) == 7 or brand_id.startswith("B") == False:
            raise serializers.ValidationError(
                "Invalid Brand ID, Brand IDs must be 7 characters long and starting with the letter B.")

    def validate(self, data):
        email_address = data["email_address"]
        phone_number = data["phone_number"]

        raise serializers.ValidationError(
            {"email_or_phone": "phone_number or email_address did not match the record for that brand ID, please try again."}
        )

        # call TCR api
        return data
