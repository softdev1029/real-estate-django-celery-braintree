from import_export import resources

from sherpa.models import UserProfile


class UserProfileResource(resources.ModelResource):
    class Meta:
        model = UserProfile
