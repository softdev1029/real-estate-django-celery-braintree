from djoser.utils import decode_uid
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.tokens import default_token_generator
from django.core import exceptions as django_exceptions
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from core.utils import clean_phone
from sherpa.models import InvitationCode, UserFeatureNotification, UserProfile


User = get_user_model()


class NewUserSerializer(serializers.Serializer):
    """
    Base user creation serializer used in both the normal registration process and when a user
    comes in through an invitations.
    """
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone = serializers.CharField(write_only=True)
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
    )

    def validate(self, attrs):
        has_code = 'invite_code' in attrs
        phone = attrs.pop('phone')
        invite_code = attrs.pop('invite_code', None)
        user = User(**attrs)
        password = attrs.get('password')

        try:
            validate_password(password, user)
        except django_exceptions.ValidationError as e:
            serializer_error = serializers.as_serializer_error(e)
            raise serializers.ValidationError(
                {'password': serializer_error['non_field_errors']},
            )
        attrs['phone'] = phone
        if has_code:
            attrs['invite_code'] = invite_code

        return attrs


class UserRegistrationSerializer(NewUserSerializer):
    """
    Used during the normal registering process.  This will create a new user.
    """
    email = serializers.EmailField()
    invite_code = serializers.CharField(max_length=32, required=False, allow_blank=True)

    default_error_messages = {
        'cannot_create_user': 'Unable to create account.',
    }

    def create(self, validated_data):
        """
        Create the User and UserProfile based on the data provided.
        """
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=validated_data['email'],
                    email=validated_data['email'],
                    first_name=validated_data['first_name'],
                    last_name=validated_data['last_name'],
                    password=validated_data['password'],
                )

                user_profile = user.profile
                user_profile.phone = clean_phone(validated_data['phone'])
                user_profile.role = UserProfile.Role.MASTER_ADMIN
                user_profile.invite_code = validated_data.get('invite_code', None)
                user_profile.save()

                # User must activate account via an email before they can log in.
                user.is_active = False
                user.save(update_fields=["is_active"])
        except IntegrityError:
            self.fail('cannot_create_user')

        return user

    def validate_email(self, value):
        if User.objects.filter(Q(email=value) | Q(username=value)).exists():
            raise ValidationError('Email already in use')
        return value

    def validate_invite_code(self, value):
        if value and not InvitationCode.objects.filter(code=value, is_active=True).exists():
            return ""
        return value


class UserInvitationSerializer(NewUserSerializer):
    """
    Used during the invitation process.  A user invited this person in and their user account
    has already been created.  They are simply updating their record.
    """
    uid = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True)

    def validate_password(self, value):
        try:
            validate_password(value, self.instance)
        except django_exceptions.ValidationError:
            raise serializers.ValidationError('This password is too weak.')

        return value

    def validate(self, attrs):
        # Verify the UID and token combination is a valid for an invited user.
        try:
            uid = decode_uid(attrs['uid'])
            user = User.objects.get(id=uid)
            if user.id != self.instance.id:
                raise User.DoesNotExist
            valid_token = default_token_generator.check_token(user, attrs['token'])
            if not valid_token:
                raise serializers.ValidationError(
                    {'token': 'Bad token.'},
                )
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'uid': 'Bad UID.'},
            )
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        # User is coming from an invite and already has a user object.
        instance.first_name = validated_data['first_name']
        instance.last_name = validated_data['last_name']
        instance.set_password(validated_data['password'])
        instance.is_active = True
        instance.save(update_fields=['first_name', 'last_name', 'password', 'is_active'])

        instance.profile.phone = clean_phone(validated_data['phone'])
        instance.profile.save(update_fields=['phone'])

        return instance


class SherpaUserSerializer(serializers.ModelSerializer):
    """
    Named this way due to a conflict with djoser's `UserSerializer`.
    """
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name()

    class Meta:
        model = User
        fields = (
            'id',
            'first_name',
            'last_name',
            'full_name',
            'email',
            'last_login',
            'is_active',
        )


class UserProfileSerializer(serializers.ModelSerializer):
    user = SherpaUserSerializer()

    class Meta:
        model = UserProfile
        fields = ('id', 'user', 'phone', 'role', 'company', 'prospect_relay_count',
                  'prospect_relay_available', 'start_time', 'end_time')

    def validate_phone(self, value):
        return clean_phone(value)

    def update(self, instance, validated_data):
        """
        Update the nested user object with the user payload.
        """
        user_data = validated_data.pop('user', {})

        # Update the profile object.
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update the nested user object.
        for attr, value in user_data.items():
            setattr(instance.user, attr, value)
        instance.user.save()

        return instance


class UserFeatureNotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for listing the user associated feature notifications.
    """
    display_feature = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserFeatureNotification
        fields = "__all__"
        # The depth option should be set to an integer value
        # that indicates the depth of relationships - returns nested representation of data.
        depth = 1


class UserProfileWithoutUserSerializer(serializers.ModelSerializer):
    """
    Used for serializing a profile when the user is not wanted.
    """
    active = serializers.BooleanField(source='user__active', read_only=True)
    feature_notifications = UserFeatureNotificationSerializer(read_only=True, many=True)

    class Meta:
        model = UserProfile
        fields = ('id', 'phone', 'role', 'active', 'start_time',
                  'end_time', 'created_timestamp', 'interesting_features', 'feature_notifications')


class CurrentUserSerializer(serializers.ModelSerializer):
    """
    Serializer for a user to get their own user data.
    """
    from companies.serializers import CompanySerializer

    full_name = serializers.SerializerMethodField()
    company = CompanySerializer(read_only=True, source='profile.company')
    profile = UserProfileWithoutUserSerializer(read_only=True)

    def get_full_name(self, obj):
        return obj.get_full_name()

    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'full_name', 'company', 'profile',
                  'is_staff')


class UpdateProfileFeatureNotificationSerializer(serializers.Serializer):
    feature_notification_id = serializers.IntegerField(required=True)
    is_dismissed = serializers.BooleanField(required=False)
    is_tried = serializers.BooleanField(required=False)


class InviteUserSerializer(serializers.ModelSerializer):
    """
    Handles serialization when inviting a person to join a users company.
    """
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=UserProfile.Role.CHOICES)

    class Meta:
        model = User
        fields = ('email', 'role')

    def validate_email(self, value):
        if User.objects.filter(Q(email=value) | Q(username=value)).exists():
            raise ValidationError('Email or username already exists')
        return value


class PaymentTokenSerializer(serializers.Serializer):
    """
    Token for the frontend to create or update a payment method.
    """
    token = serializers.CharField()


class AuthenticationTokenSerializer(serializers.Serializer):
    """
    Authentication data for the access & refresh tokens.
    """
    access = serializers.CharField()
    refresh = serializers.CharField()


class CustomTokenObtainSerializer(TokenObtainPairSerializer):
    """
    Perform all the default behavior, however also send the `user_logged_in` signal after a
    successful authentication.
    """
    def validate(self, attrs):
        data = super(CustomTokenObtainSerializer, self).validate(attrs)
        user_logged_in.send(
            sender=self.user.__class__, request=self.context['request'], user=self.user,
        )
        return data
