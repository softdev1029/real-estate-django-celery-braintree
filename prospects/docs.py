from drf_yasg import openapi


campaign_prospect_query_parameters = openapi.Parameter(
    'is_priority_unread',
    openapi.IN_QUERY,
    description='Filter by is priority or has unread sms. Only accepts "true".',
    type=openapi.TYPE_STRING,
    required=False,
)

search_parameters = [
    openapi.Parameter(
        'search',
        openapi.IN_QUERY,
        description="search term (optional)",
        type=openapi.TYPE_STRING,
        required=False,
    ),
    openapi.Parameter(
        'lead_stage',
        openapi.IN_QUERY,
        description="lead stage id (optional)",
        type=openapi.TYPE_STRING,
        required=False,
    ),
]


smart_stacker_search_parameters = [
    openapi.Parameter(
        'q',
        openapi.IN_QUERY,
        description="Query search term (optional)",
        type=openapi.TYPE_STRING,
        required=False,
    ),
    openapi.Parameter(
        'page',
        openapi.IN_QUERY,
        description="Current page (optional)",
        type=openapi.TYPE_STRING,
        required=False,
    ),
    openapi.Parameter(
        'page_size',
        openapi.IN_QUERY,
        description="Page size (optional, default: 100)",
        type=openapi.TYPE_STRING,
        required=False,
    ),
]

prospect_uuid_token = openapi.Parameter(
    'token',
    openapi.IN_PATH,
    description='UUID token to identify the prospect.',
    type=openapi.TYPE_STRING,
    required=True,
)

export_prospect_params = openapi.Parameter(
    'lead_stage',
    openapi.IN_QUERY,
    description="lead stage id, `is_priority` or `is_qualified_lead` (optional)",
    type=openapi.TYPE_STRING,
)

general_id_list_param = openapi.Parameter(
    'ids',
    openapi.IN_QUERY,
    description="A comma separated list of ids.",
    type=openapi.TYPE_STRING,
)

unread_parameters = openapi.Parameter(
    'include_messages',
    openapi.IN_QUERY,
    description="Determines whether or not to get the message detail in response data.",
    type=openapi.TYPE_BOOLEAN,
)
