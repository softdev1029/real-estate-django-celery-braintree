from rest_framework import permissions


class IsUserCompany(permissions.BasePermission):
    """
    Check if the viewset object has the company of the request user.
    """
    def has_object_permission(self, request, view, obj):
        return request.user.profile.company == obj.company
