from rest_framework.permissions import BasePermission, SAFE_METHODS


class CustomTagModify(BasePermission):
    message = 'Only custom tags can be modified.'

    def has_object_permission(self, request, view, obj):
        """
        Only allow custom `ProspectTag`s to be modified.
        """
        if request.method in SAFE_METHODS:
            return True
        return obj.is_custom
