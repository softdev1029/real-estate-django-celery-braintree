from drf_yasg import openapi


def expandable_query_parameters(fields):
    """
    Return an openapi query parameter for the expandable fields.
    """
    field_len = len(fields)
    display_str = ''
    for index, field in enumerate(fields):
        display_str += f"`{field}`"
        if index + 1 < field_len:
            display_str += ', '

    return openapi.Parameter(
        'expand',
        openapi.IN_QUERY,
        description=f"Return full related objects: {display_str}",
        type=openapi.TYPE_STRING,
        required=False,
    )
