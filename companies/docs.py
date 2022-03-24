from drf_yasg import openapi


start_date_param = openapi.Parameter(
    'start_date',
    openapi.IN_QUERY,
    description="The date to begin the stats gather (yyyy-mm-dd)",
    type=openapi.TYPE_STRING,
)

end_date_param = openapi.Parameter(
    'end_date',
    openapi.IN_QUERY,
    description="The date to end the stats gather (yyyy-mm-dd)",
    type=openapi.TYPE_STRING,
)
