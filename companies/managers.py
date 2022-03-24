from django.db import transaction
from django.utils import timezone as django_tz

from core import models


class CompanyManager(models.Manager):
    @transaction.atomic
    def register(self,
                 user,
                 name,
                 real_estate_experience_rating,
                 billing_address,
                 city,
                 state,
                 zip_code,
                 invitation_code=None,
                 how_did_you_hear='',
                 timezone='US/Mountain',
                 interesting_features=None,
                 ):
        """
        Registers a new company to the supplied user.

        :param user User: User instance who will own this company.
        :param real_estate_experience_rating int: An integer that should be between one and five.
        :param invitation_code InvitationCode: An optional InvitationCode that determines the new
        companies monthly upload limit.
        :param how_did_you_hear string: An optional string detailing how the user heard
        about Sherpa.
        :param billing_address string: company billing address.
        :param city string: company billing city.
        :param state string: company billing state.
        :param zip_code string: company billing zip_code.
        :param interesting_features: list of features user is interested in
        """
        # Get default value for the monthly upload limit.
        company = self.create(
            name=name,
            real_estate_experience_rating=real_estate_experience_rating,
            how_did_you_hear=how_did_you_hear,
            billing_address=billing_address,
            city=city,
            state=state,
            zip_code=zip_code,
            invitation_code=invitation_code,
            admin_name=user.get_full_name(),
            timezone=timezone,
            enable_twilio_integration=True,
        )

        # Add company to user profile.
        profile = user.profile
        profile.is_primary = True
        profile.company = company
        profile.disclaimer_timestamp = django_tz.now()
        profile.disclaimer_signature = user.get_full_name()
        profile.save(
            update_fields=[
                'is_primary',
                'company',
                'disclaimer_timestamp',
                'disclaimer_signature',
            ],
        )

        if interesting_features:
            from sherpa.models import Features
            interesting_features = Features.objects.filter(name__in=interesting_features)
            profile.interesting_features.set(interesting_features)

        return company


class InvitationCodeManager(models.Manager):
    def get_active_code(self, invitation_code):
        """
        Locate an active invite code instance.

        :param invitation_code string: The actual code of the invite.
        """
        try:
            invitation_code = invitation_code.lower()
            # special case for Oots
            if invitation_code == 'ttp':
                invitation_code = 'ttp1'
            return self.get(is_active=True, code=invitation_code)
        except self.model.DoesNotExist:
            return self.none()
