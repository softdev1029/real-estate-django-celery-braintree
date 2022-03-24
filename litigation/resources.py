from import_export import resources

from sherpa.models import LitigatorList


class LitigatorListResource(resources.ModelResource):
    class Meta:
        model = LitigatorList
