import pytz

from django.utils.dateparse import parse_datetime

from sherpa.models import Activity
from .models import Call


def save_call_to_activity(call):
    """
    Takes a call instance and saves it to the prospects activity.

    :param call Call: The `Call` model instance to show in prospect activity.
    """

    if not call.prospect:
        return

    # We do not want to create duplicate Activity records for the same call.
    if Activity.objects.filter(related_lookup=call.call_session_id).exists():
        return

    if call.call_type == Call.CallType.CLICK_TO_CALL:
        title = Activity.Title.CLICK_TO_CALL
    elif call.call_type == Call.CallType.OUTBOUND:
        title = Activity.Title.OUTBOUND_CALL
    elif call.call_type == Call.CallType.INBOUND:
        title = Activity.Title.INBOUND_CALL
    else:
        title = Activity.Title.GENERAL_CALL

    # Sometimesd the start time can come in as a string when it's not saved yet to the database.
    if type(call.start_time) == str:
        start_time = parse_datetime(call.start_time)
    else:
        start_time = call.start_time

    # Convert the time into the company's timezone so that it can be displayed in the activity.
    timezone = pytz.timezone(call.prospect.company.timezone)
    start_time_local = start_time.astimezone(timezone)
    call_start = start_time_local.strftime("%-I:%M%P")
    if call.duration < 60:
        duration = "less than a minute."
    else:
        duration = f"for about {round(call.duration/60, 1)} minutes."
    description = f"Call began at {call_start} and lasted {duration}"

    # Update the last inbound or outbound call from campaign prospect records.
    if call.call_type == Call.CallType.OUTBOUND or call.call_type == Call.CallType.CLICK_TO_CALL:
        call.prospect.campaignprospect_set.update(last_outbound_call=start_time_local)
    elif call.call_type == Call.CallType.INBOUND:
        call.prospect.campaignprospect_set.update(last_inbound_call=start_time_local)

    return Activity.objects.create(
        prospect=call.prospect,
        title=title,
        description=description,
        icon="fa-phone",
        related_lookup=call.call_session_id,
    )
