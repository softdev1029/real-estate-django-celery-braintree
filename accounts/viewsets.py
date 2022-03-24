from djoser.signals import user_activated
from djoser.utils import decode_uid, encode_uid
from djoser.views import UserViewSet
from drf_yasg.utils import no_body, swagger_auto_schema
from rest_framework_simplejwt.tokens import RefreshToken

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.models import Site
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.mixins import ListModelMixin, UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from billing.models import Gateway
from sherpa.models import FeatureNotification, UserFeatureNotification, UserProfile
from sherpa.permissions import AdminPlusPermission
from sherpa.tasks import sherpa_send_email
from .serializers import (
    AuthenticationTokenSerializer,
    InviteUserSerializer,
    PaymentTokenSerializer,
    UpdateProfileFeatureNotificationSerializer,
    UserInvitationSerializer,
    UserProfileSerializer,
)

User = get_user_model()


class UserProfileViewSet(UpdateModelMixin, ListModelMixin, GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserProfileSerializer
    pagination_class = None

    def get_queryset(self):
        """
        Limit to the user's company profiles.
        """
        return UserProfile.objects.filter(company=self.request.user.profile.company)

    @swagger_auto_schema(request_body=no_body)
    @action(detail=False, methods=['post'])
    def agreement(self, request):
        """
        Endpoint to mark that the authenticated user is agreeing to the current user agreement.
        """
        profile = request.user.profile
        profile.update_agreement()
        profile.refresh_from_db()
        serializer = self.serializer_class(profile)
        return Response(serializer.data)

    @swagger_auto_schema(
        method='patch',
        request_body=UpdateProfileFeatureNotificationSerializer,
        responses={200: 'Successfully updated profile feature notification.'},
    )
    @action(detail=True, methods=['patch'])
    def update_profile_feature_notification(self, request, pk=None):
        """
        Endpoint to update the user profile feature notification.
        """
        profile = request.user.profile
        serializer = UpdateProfileFeatureNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feature_notification_obj = get_object_or_404(
            FeatureNotification,
            pk=serializer.validated_data.get('feature_notification_id'),
        )
        user_feature_notification_obj = get_object_or_404(
            UserFeatureNotification,
            user_profile=profile,
            feature_notification=feature_notification_obj,
        )
        if serializer.validated_data.get('is_dismissed'):
            user_feature_notification_obj.is_dismissed = True
            user_feature_notification_obj.display_count += 1
            user_feature_notification_obj.dismissed_or_tried_dt = timezone.now()
        if serializer.validated_data.get('is_tried'):
            user_feature_notification_obj.is_tried = True
            user_feature_notification_obj.dismissed_or_tried_dt = timezone.now()
        user_feature_notification_obj.save(
            update_fields=['is_dismissed', 'display_count', 'is_tried', 'dismissed_or_tried_dt'],
        )
        return Response({'detail': 'Successfully updated profile feature notification'}, status=200)


class SherpaUserViewSet(UserViewSet):
    """
    The default authentication viewsets that is extended from the Djoser UserViewSet.
    """
    pagination_class = None

    @swagger_auto_schema(responses={200: PaymentTokenSerializer})
    @action(detail=False, methods=['get'], permission_classes=[AdminPlusPermission])
    def payment_token(self, request):
        """
        Get the payment method token to create or update a payment method.
        """
        braintree_id = request.user.profile.company.braintree_id
        if braintree_id:
            token = Gateway.client_token.generate({'customer_id': braintree_id})
        else:
            token = Gateway.client_token.generate()

        serializer = PaymentTokenSerializer({"token": token})
        return Response(serializer.data)

    @swagger_auto_schema(responses={200: AuthenticationTokenSerializer})
    @action(detail=False, methods=["post"])
    def activation(self, request, *args, **kwargs):
        """
        auth_users_activation

        Verify the email of a newly created account and activate their account.

        ---

        In order to attach the authentication token to the activation response, we need to override
        the view from djoser as well as get the refresh token from our simplejwt package.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Activate the user if the serializer token/uid were valid.
        user = serializer.user
        user.is_active = True
        user.save()
        user_activated.send(sender=self.__class__, user=user, request=self.request)

        # Create the token and return it in the response.
        refresh = RefreshToken.for_user(user)
        token_data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
        return Response(token_data)

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[AdminPlusPermission],
        serializer_class=InviteUserSerializer,
    )
    def invite(self, request):
        """
        Invite a person to join the company in the system.  The invited person user account will
        be created and an email detailing what they need to do to finish registering will be sent
        out.
        """
        serializer = InviteUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data.get('email')
        role = serializer.validated_data.get('role')
        password = User.objects.make_random_password()

        user = User.objects.create_user(email, email, password)
        user.profile.role = role
        user.profile.company = request.user.profile.company
        user.profile.save(update_fields=['role', 'company'])

        user.is_active = False
        user.save(update_fields=['is_active'])

        # Get the frontend site
        site = Site.objects.get(id=settings.DJOSER_SITE_ID)
        uid = encode_uid(user.pk)
        token = default_token_generator.make_token(user)
        invite_url = f'{ site.domain }/invite/'

        sherpa_send_email.delay(
            f"You've been invited to join { user.profile.company.name } at Sherpa!",
            'email/email_invite_user.html',
            user.email,
            {
                'invite_url': invite_url,
                'inviter': request.user.get_full_name(),
                'uid': uid,
                'token': token,
                'company_name': request.user.profile.company.name,
            },
        )

        return Response({'id': user.id}, 201)

    @action(detail=True, methods=['post'], permission_classes=[])
    def invitation(self, request, pk=None):
        """
        Accepts an invitation by updating their information and activating their user account.
        """
        user = self.get_object()
        serializer = UserInvitationSerializer(user, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        user.last_login = timezone.now()
        user.save()
        user_activated.send(sender=self.__class__, user=user, request=self.request)

        refresh = RefreshToken.for_user(user)
        token_data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
        return Response(token_data)

    @action(detail=False, methods=['get'], permission_classes=[])
    def verify_invite(self, request):
        uid = request.query_params.get('uid', None)
        token = request.query_params.get('token', None)

        if not uid or not token:
            return Response({'detail': 'Must pass `uid` and `token`'}, status=400)

        userid = decode_uid(uid)
        try:
            user = User.objects.get(id=userid)
        except User.DoesNotExist:
            return Response({'detail': 'Invalid `uid` passed.'}, status=400)

        if user.is_active:
            return Response({'detail': 'Invalid `uid` passed.'}, status=400)

        valid_token = default_token_generator.check_token(user, token)
        if not valid_token:
            return Response({'detail': 'Invalid `token` passed.'}, status=400)

        payload = {
            'id': user.pk,
            'email': user.email,
        }
        return Response(payload)
