from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import CustomTokenObtainSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Override the jwt obtain pair view so that we can send the django logged in signal.

    Djoser just references the views from django-rest-framework-simplejwt and they have decided
    against sending the `user_logged_in` signal as outlined in issue#190[0] and PR#196[1]

    [0] https://github.com/SimpleJWT/django-rest-framework-simplejwt/issues/190
    [1] https://github.com/SimpleJWT/django-rest-framework-simplejwt/pull/196
    """
    serializer_class = CustomTokenObtainSerializer
