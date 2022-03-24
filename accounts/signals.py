from ipware import get_client_ip

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save

from sherpa.models import UserProfile
from .models import UserLogin
from .tasks import modify_freshsuccess_user


def record_login(sender, user, request, **kwargs):
    """
    Track when users login and from what IP address.
    """
    ip_address = get_client_ip(request)[0]
    UserLogin.objects.create(user=user, ip_address=ip_address)


def user_profile_post_save(sender, instance, created, raw, **kwargs):
    """
    Create a freshsuccess product user when a new user profile is created in sherpa.
    """
    if not created or raw:
        return

    # When profiles are first created, they don't have a company yet.
    if instance.company:
        modify_freshsuccess_user.delay(instance.user.id)


user_logged_in.connect(record_login)
post_save.connect(user_profile_post_save, sender=UserProfile)
