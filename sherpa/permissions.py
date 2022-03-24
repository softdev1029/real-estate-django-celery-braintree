from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import Company, UserProfile


class HasPaymentPermission(BasePermission):
    message = 'Active subscription required to use this endpoint.'

    def has_permission(self, request, view):
        """
        Only allow companies with active subscriptions to access the endpoint, unless they are
        exempt.
        """
        company = request.user.profile.company
        if company.is_billing_exempt:
            return True
        return company.subscription_status == Company.SubscriptionStatus.ACTIVE


class RoleBasePermission(BasePermission):
    """
    Base permission class that should be inherited by all of the role permission classes.
    """
    master_admin = UserProfile.Role.MASTER_ADMIN
    admin = UserProfile.Role.ADMIN
    staff = UserProfile.Role.STAFF
    junior_staff = UserProfile.Role.JUNIOR_STAFF


class AdminPlusPermission(RoleBasePermission):
    """
    Only allows user to use endpoint if they have admin+ role.
    """
    def has_permission(self, request, view):
        """
        Only allow staff+ users to perform actions.
        """
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.profile.role in [self.admin, self.master_admin]


class AdminPlusModifyPermission(RoleBasePermission):
    """
    Permission to apply when only admin+ users should be able to modify the viewset objects.
    """
    def has_permission(self, request, view):
        """
        Only allow staff+ users to perform non-safe actions on the viewset.
        """
        if request.method in SAFE_METHODS:
            return True

        return request.user.profile.role in [self.admin, self.master_admin]


class StaffPlusModifyPermission(RoleBasePermission):
    """
    Permission to apply when only user is not junior staff
    """
    def has_permission(self, request, view):
        """
        Only allow staff+ users to perform non-safe actions on the viewset.
        """
        if request.user.is_authenticated:
            if request.method in SAFE_METHODS:
                return True

            return request.user.profile.role != self.junior_staff

        return False
