from datetime import datetime, time, timedelta
from time import sleep
import uuid

from drf_yasg.utils import swagger_auto_schema
import pytz
from telnyx.error import APIError, InvalidParametersError
from twilio.twiml.voice_response import Dial, VoiceResponse

from django.db.models import DateTimeField, F
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.mixins import CreateModelMixin, ListModelMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from accounts.serializers import PaymentTokenSerializer
from core.models.expressions import ToLocalTZ
from phone.choices import Provider
from prospects.serializers import ProspectActivitySerializer
from sms.clients import TelnyxClient
from sms.utils import get_webhook_url
from .models import Call
from .serializers import CallSerializer
from .tasks import save_recording_to_s3
from .utils import save_call_to_activity


class CallViewSet(CreateModelMixin, ListModelMixin, GenericViewSet):
    """
    Endpoint for call logging purposes.
    """
    serializer_class = CallSerializer
    permission_classes = (IsAuthenticated,)
    model = Call

    def get_queryset(self):
        """
        Filter call instances based on prospect company.
        """
        try:
            start_date = datetime.strptime(
                self.request.query_params.get('start_date'),
                '%Y-%m-%d',
            )
        except (TypeError, ValueError):
            start_date = timezone.now() - timedelta(days=7)

        try:
            end_date = datetime.strptime(
                self.request.query_params.get('end_date'),
                '%Y-%m-%d',
            )
        except (TypeError, ValueError):
            end_date = timezone.now()

        company = self.request.user.profile.company
        local_tz = pytz.timezone(company.timezone)
        start_date = datetime.combine(start_date, time.min, local_tz)
        end_date = datetime.combine(end_date, time.max, local_tz)

        return Call.objects.annotate(
            local_dt=ToLocalTZ(
                [F('start_time'), F('prospect__company__timezone')], output_field=DateTimeField(),
            ),
        ).filter(
            prospect__company=company,
            local_dt__range=[start_date, end_date],
        ).order_by('-start_time')

    @swagger_auto_schema(responses={201: ProspectActivitySerializer})
    def create(self, request):
        """
        Creates a `Call` instance and generates and returns an `Activity` instance.
        """
        agent_profile = request.user.profile
        context = {'request': request}
        serializer = CallSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        call = serializer.save(agent_profile=agent_profile, call_type=Call.CallType.CLICK_TO_CALL)

        activity = save_call_to_activity(call)
        serializer = ProspectActivitySerializer(activity)
        return Response(serializer.data, status=201)

    @action(detail=False, permission_classes=[AllowAny], methods=['post'])  # noqa: C901
    def received_telnyx(self, request):
        """
        Receive the webhook request sent from telnyx.

        Each event of the call will send a request to this endpoint, and the whole call is defined
        by the unique `call_control_id`.

        Note: need to always return status code 200, or else telnyx will retry the request.
        """

        # For some reason the request data is different on dev vs production
        if 'payload' in request.data:
            payload = request.data.get('payload')
            event_type = request.data.get('event_type')
        else:
            payload = request.data.get('data').get('payload')
            event_type = request.data.get('data').get('event_type')

        from_number = payload.get('from')
        to_number = payload.get('to')
        start_time = payload.get('start_time')
        end_time = payload.get('end_time')
        call_control_id = payload.get('call_control_id')
        call_session_id = payload.get('call_session_id')

        # Either create the instance or get it if it already exists so that it can be updated.
        instance, created = Call.objects.get_or_create(
            call_session_id=call_session_id,
            defaults={
                'call_control_id': call_control_id,
                'start_time': start_time,
                'from_number': from_number,
                'to_number': to_number,
            },
        )

        # Fetch the call object. This is Telnyx specific and is fine to leave this for now.
        # will change when we refactor to be more scalable.
        client = TelnyxClient()

        try:
            call = client.retrieve_call(call_control_id)
        except APIError:
            # Sometimes the Telnyx api has connection issues here.
            instance.error = Call.ErrorType.TELNYX_API_ERROR
            instance.save(update_fields=['error'])
            return Response({'detail': 'Telnyx API connection error'})

        # Save start/end time if it's not already on the call session.
        if start_time and not instance.start_time:
            instance.start_time = start_time
            instance.save(update_fields=['start_time'])
        if end_time and not instance.end_time:
            instance.end_time = end_time
            instance.save(update_fields=['end_time'])

        # Identify the prospect that is calling.
        if not instance.prospect:
            sherpa_phone = instance.assign_sherpa_phone()
            if not sherpa_phone:
                try:
                    call.hangup()
                except (InvalidParametersError, APIError):
                    pass
                return Response({'detail': f'No sherpa phone found for a call to {to_number}.'})

            # Reject calls that are not from a prospect if company has the setting.
            prospect = instance.assign_prospect()
            if any([
                not prospect and sherpa_phone.company.block_unknown_calls,
                prospect and prospect.is_blocked,
            ]):
                if call.is_alive:
                    try:
                        call.answer()
                        call.speak(
                            payload="the number you're calling from is unrecognized, goodbye",
                            voice="female",
                            language="en-US",
                        )
                        sleep(3)
                        call.hangup()
                    except (InvalidParametersError, APIError):
                        pass
                return Response({'detail': f'No prospect found with phone number {from_number}.'})

        # Forward the initiated call if we have a forwarding number.
        if not instance.call_forwarding_number:
            instance.error = Call.ErrorType.NO_FORWARDING
            instance.save(update_fields=['error'])

            try:
                call.hangup()
            except InvalidParametersError:
                pass

            return Response({
                'detail': f'No forwarding number for {to_number}.',
            })

        # Transfer the call to the call forwarding number.
        if created:
            instance.forward(client, call, instance.call_forwarding_number)

        # Save call to activity if call has a prospect and duration.
        if event_type == 'call.hangup' and instance.prospect:
            save_call_to_activity(instance)

        # Record the call if the company has turned it on.
        if all([
            event_type == 'call.answered',
            instance.prospect and instance.prospect.company.record_calls,
        ]):
            call.record_start(format="mp3", channels="single")

        # The final webhook call will include the recording URL.
        if event_type == 'call.recording.saved':
            url = payload.get('recording_urls').get('mp3')
            if url:
                save_recording_to_s3.delay(instance.id, url)

        return Response({})

    @action(detail=False, permission_classes=[AllowAny], methods=['post'])  # noqa: C901
    def received_twilio(self, request):
        """
        Receive the webhook request sent from twilio.

        Each event of the call will send a request to this endpoint, and the whole call is defined
        by the unique `call_control_id`.
        """
        call_sid = request.data.get('_call_sid')
        to_number = request.data.get('_called')
        from_number = request.data.get('_caller')
        # Either create the instance or get it if it already exists so that it can be updated.
        instance, created = Call.objects.get_or_create(
            call_control_id=call_sid,
            defaults={
                'call_session_id': uuid.uuid4(),
                'from_number': from_number,
                'to_number': to_number,
            },
        )

        # Start a voice response,
        response = VoiceResponse()

        # Get the sherpa phone so we can identify the company the phone is tied to.
        instance.assign_sherpa_phone()
        if not instance.sherpa_phone:
            return HttpResponse(response)

        client = instance.sherpa_phone.client
        if not client:
            return HttpResponse(response)

        # Get current call and update start time and end time if available.
        call = client.client.calls(call_sid).fetch()
        start_time = call.start_time
        end_time = call.end_time
        if start_time and not instance.start_time:
            instance.start_time = start_time
            instance.save(update_fields=['start_time'])
        if end_time and not instance.end_time:
            instance.end_time = end_time
            instance.save(update_fields=['end_time'])

        # Identify the prospect that is calling.
        if not instance.prospect:
            # Reject calls that are not from a prospect if company has the setting.
            prospect = instance.assign_prospect()
            if any([
                not prospect and instance.sherpa_phone.company.block_unknown_calls,
                prospect and prospect.is_blocked,
            ]):
                response.say(
                    "the number you're calling from is unrecognized, goodbye",
                    voice="female",
                    language="en-US",
                )
                return HttpResponse(response)

        # Forward the initiated call if we have a forwarding number.
        if not instance.call_forwarding_number:
            instance.error = Call.ErrorType.NO_FORWARDING
            instance.save(update_fields=['error'])
            return HttpResponse(response)

        # Transfer the call to the call forwarding number.
        if created:
            forward_to = instance.call_forwarding_number if instance.call_forwarding_number\
                .startswith("+1") else f'+1{instance.call_forwarding_number}'
            record = 'record-from-answer' if instance.prospect and instance.prospect.company\
                .record_calls else 'do-not-record'
            response_url = get_webhook_url(Provider.TWILIO, 'voice')
            dial = Dial(
                record=record,
                recording_status_callback=response_url,
                action=response_url,
                number=forward_to,
            )
            response.append(dial)

        # Save call to activity if call is completed.
        if call.status == 'completed':
            save_call_to_activity(instance)

        # The final webhook call will include the recording URL.
        if request.data.get('_recording_status') == 'completed' and request.data.get(
                '_recording_url'):
            save_recording_to_s3.delay(instance.id, request.data.get('_recording_url'))

        return HttpResponse(response)

    @swagger_auto_schema(responses={200: PaymentTokenSerializer})
    @action(detail=False, methods=['get'], pagination_class=None)
    def token(self, request):
        """
        Gets and returns a Telnyx WebRTC JWT Token.
        """
        # This is Telnyx specific and is fine to leave this for now.
        # will change when we refactor to be more scalable.
        token = TelnyxClient.create_c2c_token()
        if not token:
            return Response({}, 400)
        return Response({'token': token})
