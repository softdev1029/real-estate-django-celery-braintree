from djoser.email import ActivationEmail, PasswordResetEmail

from django.conf import settings
from django.contrib.sites.models import Site


class OverrideDjoserSiteMixin:
    def get_context_data(self):
        """
        Need to override the `Site` data in context to use the second site instead of first, which
        is rendered by default.

        The reason for this is that both legacy and new Sherpa use packages that utilize the
        `SITE_ID` to render the auth-specific emails, and we need to maintain compatibility
        (temporarily) for both having different sites. When legacy is no longer in use, we should
        be able to remove this class and switch `SITE_ID` in settings to be 2 rather than 1.
        """
        context = super().get_context_data()
        user = context.get("user")
        site = Site.objects.get(id=settings.DJOSER_SITE_ID)
        context["site_name"] = site.name
        context["domain"] = site.domain
        context["invite_code"] = user.profile.invite_code
        return context


class SherpaActivationEmail(OverrideDjoserSiteMixin, ActivationEmail):
    template_name = 'email/account_activation.html'


class SherpaPasswordResetEmail(OverrideDjoserSiteMixin, PasswordResetEmail):
    pass
