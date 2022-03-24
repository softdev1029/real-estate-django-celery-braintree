from drf_yasg import openapi


market_availability_query_parameters = openapi.Parameter(
    'area_code_state_id',
    openapi.IN_QUERY,
    description='Unique ID of AreaCodeState object',
    type=openapi.TYPE_INTEGER,
    required=True,
)

market_number_availability_query_parameters = openapi.Parameter(
    'quantity',
    openapi.IN_QUERY,
    description='How many numbers to check are available for the market',
    type=openapi.TYPE_INTEGER,
    required=True,
)

market_best_effort_query_parameter = openapi.Parameter(
    'best_effort',
    openapi.IN_QUERY,
    description='Determines if request should pad numbers with nearby area codes to fill quantity',
    type=openapi.TYPE_BOOLEAN,
    required=False,
    default=False,
)

market_return_phone_numbers_query_parameter = openapi.Parameter(
    'return_numbers',
    openapi.IN_QUERY,
    description='Determines if the response should include a list of possible found phone numbers',
    type=openapi.TYPE_BOOLEAN,
    required=False,
    default=False,
)
