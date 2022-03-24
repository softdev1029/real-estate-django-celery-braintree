from telnyx.error import InvalidRequestError

from django.conf import settings
from django.utils import timezone as django_tz
from django.utils.functional import cached_property

from core import models
from phone.choices import Provider
from sherpa.abstracts import AbstractTag
from sms.clients import get_client


class ProspectTag(AbstractTag):
    """
    Tags that a company has for labeling and grouping prospects.
    """
    @property
    def prospect_count(self):
        return self.prospect_set.count()


class RelayNumber(models.Model):
    """
    Numbers to use for prospect relay.
    """
    class Status:
        ACTIVE = 'active'
        PENDING = 'pending'
        INACTIVE = 'inactive'
        RELEASED = 'released'

        CHOICES = (
            (ACTIVE, 'Active'),
            (PENDING, 'Pending'),
            (INACTIVE, 'Inactive'),
            (RELEASED, 'Released'),
        )

    created = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        default=Status.ACTIVE,
        max_length=16,
        db_index=True,
        choices=Status.CHOICES,
    )
    phone = models.CharField(max_length=16, db_index=True)
    provider_id = models.CharField(max_length=125)

    @cached_property
    def client(self):
        """
        We currently only have this setup on Telnyx. We will need to add a provider field
        on this model to make it scalable. But let's go ahead and use `get_client`
        """
        return get_client(provider=Provider.TELNYX)


class ProspectRelay(models.Model):
    """
    Relay connection between an agent (`UserProfile`) and a `Prospect`.
    """
    prospect = models.ForeignKey('sherpa.Prospect', on_delete=models.CASCADE)
    agent_profile = models.ForeignKey(
        'sherpa.UserProfile',
        on_delete=models.CASCADE,
        help_text='Profile of the agent who is connected to the prospect.',
    )
    relay_number = models.ForeignKey(RelayNumber, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(null=True, blank=True)

    @staticmethod
    def connect(agent, prospect):
        """
        Create connection between agent and prospect.

        :return: `ProspectRelay` object if successful or None if not successful.
        :return: string with error message or None if successful.
        """
        # Get unavailable numbers - these are numbers this agent is already using.
        unavailable_numbers = ProspectRelay.objects.filter(
            agent_profile__phone=agent.phone,
        ).values_list('relay_number__phone', flat=True)

        # Check if agent is already using max connections.
        if len(unavailable_numbers) >= settings.TELNYX_RELAY_CONNECTIONS:
            return None, 'max_assignment_limit_reached'

        # Available numbers are active numbers not yet used by this agent.
        available_numbers = RelayNumber.objects.filter(status=RelayNumber.Status.ACTIVE).exclude(
            phone__in=unavailable_numbers)

        # Return error message if there's no available numbers.
        if not available_numbers:
            return None, 'no_available_relay_numbers'

        # Alert agent that connection has been added and create connection.
        relay_number = available_numbers.first()
        message = f"** CONNECTED ** {prospect.get_full_name()} - {prospect.phone_display} " \
                  f"has been ADDED to this SMS relay stream. The conversation will be shown here " \
                  f"and in the Lead Sherpa console."
        url = settings.APP_URL + prospect.get_absolute_url()
        messages = [message, url]
        client = relay_number.client
        to_number = f'+1{agent.phone}'
        from_number = f'+1{relay_number.phone}'
        for message in messages:
            client.send_message(to=to_number, from_=from_number, body=message)

        return ProspectRelay.objects.create(
            prospect=prospect,
            agent_profile=agent,
            relay_number=relay_number,
        ), None

    def disconnect(self):
        """
        Disconnect relay connection and alert agent.
        """
        if self.rep_phone:
            message = (
                f"** DISCONNECTED ** {self.prospect.get_full_name()} - "
                "{self.prospect.phone_display} has been REMOVED from this SMS relay stream. The "
                "conversation will continue in the Lead Sherpa console only."
            )
            try:
                self._send(to=self.rep_phone, from_=self.relay_phone, body=message)
            except InvalidRequestError:
                pass

        self.delete()

    def send(self, message, media_url=None):
        """
        Send relayed message from prospect to rep.
        """
        if media_url and message == 'no_text':
            message = 'image attached'

        from_prefix = f'From {self.prospect.get_full_name()} {self.prospect.phone_display}'
        self._send(
            to=self.rep_phone,
            from_=self.relay_phone,
            body=f"{from_prefix}: {message}",
            media_url=media_url,
        )
        self._update_last_activity()

    def send_from_rep(self, message, media_url=None):
        """
        Send relayed message from rep to prospect.
        """
        from sherpa.models import SMSMessage

        try:
            self._send(
                to=self.prospect_phone,
                from_=self.sherpa_phone,
                body=message,
                media_url=media_url,
            )
            SMSMessage.objects.create(
                our_number=self.sherpa_phone,
                contact_number=self.prospect_phone,
                from_number=self.sherpa_phone,
                to_number=self.prospect_phone,
                message=message,
                prospect=self.prospect,
                user=self.agent_profile.user,
                company=self.prospect.company,
                media_url=media_url,
            )
            self._update_last_activity()
        except InvalidRequestError:
            pass

    def _send(self, to, from_, body, media_url=None):
        """
        Send relayed message.
        """
        self.relay_number.client.send_message(to=to, from_=from_, body=body, media_url=media_url)

    def _update_last_activity(self):
        """
        Update last activity date.
        """
        self.last_activity = django_tz.now()
        self.save(update_fields=['last_activity'])

    @property
    def relay_phone(self):
        return f'+1{self.relay_number.phone}'

    @property
    def rep_phone(self):
        return f'+1{self.agent_profile.phone}'

    @property
    def sherpa_phone(self):
        return f'+1{self.prospect.sherpa_phone_number_obj.phone}'

    @property
    def prospect_phone(self):
        return f'+1{self.prospect.phone_raw}'

    @property
    def campaign_prospect(self):
        """
        First `CampaignProspect` associated with this `Prospect`.
        """
        return self.prospect.campaignprospect_set.order_by('-id').first()


class ProspectTagAssignment(models.Model):
    """
    Relation between prospect and tag allowing to add extra data about when the tag was assigned.
    """
    tag = models.ForeignKey(ProspectTag, on_delete=models.CASCADE)
    prospect = models.ForeignKey('sherpa.Prospect', on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tag', 'prospect')

    def __str__(self):
        return f'{self.tag.name} on {self.assigned_at}'
