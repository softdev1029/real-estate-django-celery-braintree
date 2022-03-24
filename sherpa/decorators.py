from django.contrib.auth.decorators import user_passes_test

from .models import UserProfile


def role_required(*roles):
    if len(roles) == 1 and isinstance(roles[0], (list, tuple)):
        roles = roles[0]

    def check_role(user):
        if not user.is_authenticated:
            return False

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile.role in roles

    return user_passes_test(check_role, login_url='/accounts/login/role/')
