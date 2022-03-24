from drf_yasg import openapi


export_params = [
    openapi.Parameter(
        'phone_type',
        openapi.IN_QUERY,
        description="""
            Which phone type to export. Valid choices: 'all', 'mobile', 'landline', 'other',
            'litigator', 'dnc'.
        """,
        type=openapi.TYPE_STRING,
    ),
    openapi.Parameter(
        'lead_stage',
        openapi.IN_QUERY,
        description="Filter campaign prospects by lead stage id",
        type=openapi.TYPE_STRING,
    ),
    openapi.Parameter(
        'is_priority_unread',
        openapi.IN_QUERY,
        description="Filter campaign prospects by is_priority and has_unread_sms",
        type=openapi.TYPE_STRING,
    ),
]

batch_prospects_params = [
    openapi.Parameter(
        'sms_template',
        openapi.IN_QUERY,
        description="Id of the sms template to use for batch prospects.",
        type=openapi.TYPE_NUMBER,
    ),
]

start_upload_params = [
    openapi.Parameter(
        'tags',
        openapi.IN_QUERY,
        description="Comma separated string of tag ids to append to prospects.",
        type=openapi.TYPE_STRING,
    ),
    openapi.Parameter(
        'campaign',
        openapi.IN_QUERY,
        description="ID of Campaign to upload to",
        type=openapi.TYPE_NUMBER,
    ),
]

direct_mail_params = [
    openapi.Parameter(
        'provider',
        openapi.IN_QUERY,
        description="API provider to use for Direct Mail",
        type=openapi.TYPE_STRING,
    ),
]
yellow_letter_params = [
    openapi.Parameter(
        'date',
        openapi.IN_QUERY,
        description="Target date to check",
        type=openapi.TYPE_STRING,
    ),
]
