import uuid

from telnyx.error import APIError, InvalidParametersError, PermissionError

from django.utils.dateparse import parse_datetime

from core import models
from prospects.models import ProspectRelay
from sms.utils import telnyx_error_has_error_code


def recording_path(instance, filename):
    if instance.sherpa_phone:
        return f'companies/{instance.sherpa_phone.company.uuid}/recordings/{filename}'


class Call(models.Model):
    """
    When we receive calls to our phone numbers, there is processing that needs to happen and this is
    the model that will store data about that incoming call.

    For more information on understanding Telnyx calls:
    https://developers.telnyx.com/docs/v2/call-control
    """
    class ErrorType:
        NO_SHERPA_PHONE = 'no_sherpa_phone'
        NO_FORWARDING = 'no_forwarding'
        ERROR_FORWARDING = 'error_forwarding'
        NO_PROSPECT = 'no_prospect'
        NO_AGENT = 'no_agent'
        TELNYX_API_ERROR = 'api_error'
        DUPLICATE_PHONE = 'duplicate_phone'
        CALL_INACTIVE = 'call_inactive'

        CHOICES = (
            (NO_SHERPA_PHONE, 'No Sherpa Phone'),
            (NO_FORWARDING, 'No Forwarding Number'),
            (ERROR_FORWARDING, 'Error Forwarding'),
            (NO_PROSPECT, 'No Prospect'),
            (NO_AGENT, 'No Agent'),
            (TELNYX_API_ERROR, 'Telnyx API Error'),
            (DUPLICATE_PHONE, ' Duplicate Phone'),
            (CALL_INACTIVE, 'Call Inactive'),
        )

    class CallType:
        OUTBOUND = 'outbound'
        INBOUND = 'inbound'
        CLICK_TO_CALL = 'click_to_call'

        CHOICES = (
            (OUTBOUND, 'Outbound'),
            (INBOUND, 'Inbound'),
            (CLICK_TO_CALL, 'Click to Call'),
        )

    call_control_id = models.CharField(max_length=64, unique=True, db_index=True, null=True)
    call_session_id = models.UUIDField(
        max_length=64,
        db_index=True,
        default=uuid.uuid4,
        editable=False,
    )
    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)
    from_number = models.CharField(max_length=64, null=True)
    to_number = models.CharField(max_length=16)

    # Technically we could get the prospect from the from/to number, however this can change through
    # a variety of ways, such as changing a prospect's number or releasing a number.
    prospect = models.ForeignKey('sherpa.Prospect', null=True, blank=True,
                                 on_delete=models.SET_NULL)
    agent_profile = models.ForeignKey(
        'sherpa.UserProfile',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Agent's actual phone that the call was forwared to.
    # We could get the forwarded_number from the prospect record, however it's possible that it has
    # changed from the time the call was made and when retrieving the record.
    forwarded_number = models.CharField(max_length=16, blank=True)

    # The sherpa phone record that the call was associated with.
    sherpa_phone = models.ForeignKey('sherpa.PhoneNumber', blank=True, null=True,
                                     on_delete=models.SET_NULL)

    error = models.CharField(max_length=16, blank=True, choices=ErrorType.CHOICES)
    recording = models.FileField(upload_to=recording_path, null=True, blank=True)
    call_type = models.CharField(max_length=32, choices=CallType.CHOICES, null=True, blank=True)

    @property
    def duration(self):
        """
        Return the duration in seconds of the phone call.
        """
        if not self.end_time or not self.start_time:
            return None

        # Sometimes the instance end_time can be saved as a string before it's saved to database.
        if type(self.end_time) == str:
            self.end_time = parse_datetime(self.end_time)
        if type(self.start_time) == str:
            self.start_time = parse_datetime(self.start_time)

        delta = self.end_time - self.start_time
        return delta.seconds

    @property
    def from_number_raw(self):
        return self.from_number.replace('+1', '')

    @property
    def to_number_raw(self):
        return self.to_number.replace('+1', '')

    @property
    def call_forwarding_number(self):
        """
        Return the call forwarding number for the destination number.

        The progression is:
        1) Prospect's phone if this is an agent calling a relay number
        2) Prospect's call forwarding number
        3) Market's call forwarding number
        4) Company's call forwarding number
        """

        if self.relay:
            return self.relay.prospect_phone

        if self.prospect:
            prospect_call_forwarding_number = self.prospect.call_forwarding_number
            if prospect_call_forwarding_number:
                return f'+1{prospect_call_forwarding_number}'

        market_cf_number = self.sherpa_phone.market.call_forwarding_number
        if market_cf_number:
            return market_cf_number

        return self.sherpa_phone.company.call_forwarding_number if self.sherpa_phone else None

    @property
    def relay(self):
        """
        If an agent is calling a prospect through a relay, return the `ProspectRelay` object.
        """

        return ProspectRelay.objects.filter(
            agent_profile__phone=self.from_number_raw,
            relay_number__phone=self.to_number_raw,
        ).first()

    def forward(self, client, call, to_number):
        """
        Forward the call to another provided phone number.

        :arg client TelnyxClient: instance of the client to transfer the call.
        :arg call TelnyxCall: instance of a telnyx call object.
        :arg to_number string: +1e64 number to forward the number to..
        """
        to_number = to_number if to_number.startswith("+1") else f'+1{to_number}'
        if client.is_production:
            # Use relay number as 'from' if there's a relay to mask the agent's personal phone.
            from_number = self.from_number
            if self.relay:
                from_number = self.relay.sherpa_phone
            kwargs = {"to": to_number, "from": from_number}
            try:
                call.transfer(**kwargs)
            except (APIError, InvalidParametersError, PermissionError) as e:
                # The call is not alive.
                self.error = self.ErrorType.TELNYX_API_ERROR
                if telnyx_error_has_error_code(e, '90018'):
                    self.error = self.ErrorType.CALL_INACTIVE
                self.save(update_fields=['error'])
                return
        self.forwarded_number = to_number
        return self.save(update_fields=['forwarded_number'])

    def track_event(self, event_type):
        """
        Append the call event to the instance's event stream.

        This is no longer used, however let's keep it for now in case we need further knowledge of
        which events happen on the call session. Requires adding an ArrayField for `events`.
        """
        events = self.events
        if events is None:
            events = []
        self.append(event_type)
        self.events = events
        self.save(update_fields=['events'])

    def assign_sherpa_phone(self):
        """
        Find the sherpa `PhoneNumber` record that the call is connected to, based on the from and to
        numbers. This also helps get the company and assign the prospect.

        :return: Return either the phone record if there is one, or None if no valid phone record.
        """
        from sherpa.models import PhoneNumber

        if self.sherpa_phone:
            return self.sherpa_phone

        cleaned_number = self.to_number.replace("+1", "")
        if self.relay:
            cleaned_number = self.relay.prospect.sherpa_phone_number_obj.phone
        try:
            phone_record = PhoneNumber.objects.get(
                phone=cleaned_number,
                status__in=[PhoneNumber.Status.ACTIVE, PhoneNumber.Status.INACTIVE],
            )
        except PhoneNumber.DoesNotExist:
            self.error = self.ErrorType.NO_SHERPA_PHONE
            self.save(update_fields=['error'])
            return
        except PhoneNumber.MultipleObjectsReturned:
            self.error = self.ErrorType.DUPLICATE_PHONE
            self.save(update_fields=['error'])
            return

        self.sherpa_phone = phone_record
        self.save(update_fields=['sherpa_phone'])
        return self.sherpa_phone

    def assign_prospect(self):
        """
        After the sherpa phone number (and indirectly company) are found, then we can search on the
        from phone number to find the prospect and which number to forward to.

        :return: Return either the prospect if there is one, or None if no found prospect.
        """
        from sherpa.models import Prospect

        agent_profile = None
        if self.relay:
            prospect = self.relay.prospect
            agent_profile = self.relay.agent_profile
            call_type = self.CallType.OUTBOUND
        else:
            #  Some companies have multiple Prospect with the same phone.  Unfortunately there is
            #  no easy way to determine which prospect is calling so we'll just grab the last.
            prospect_filter = Prospect.objects.filter(
                phone_raw=self.from_number_raw,
                company=self.sherpa_phone.market.company,
            )

            #  We must always locate a prospect.  If not, flag the error and return.
            if not prospect_filter.exists():
                self.error = self.ErrorType.NO_PROSPECT
                self.save(update_fields=['error'])
                return

            prospect = prospect_filter.last()

            #  Find agent via ProspectRelay.
            relay = ProspectRelay.objects.filter(
                prospect=prospect,
                prospect__sherpa_phone_number_obj__phone=self.to_number_raw,
            )
            if relay.exists():
                relay = relay.first()
                agent_profile = relay.agent_profile
            call_type = self.CallType.INBOUND

        self.prospect = prospect
        self.agent_profile = agent_profile
        self.call_type = call_type
        self.save(update_fields=['prospect', 'agent_profile', 'call_type'])

        return self.prospect
