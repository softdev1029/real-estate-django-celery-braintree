from .models import UserProfile


def profile(request):
    p = None
    if request.user.is_authenticated:
        p, _ = UserProfile.objects.get_or_create(user=request.user)
    return {'profile': p}
