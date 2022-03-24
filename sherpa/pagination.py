from rest_framework.pagination import PageNumberPagination


class SherpaPagination(PageNumberPagination):
    """
    Default pagination to use in entirety of the sherpa api project.
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 100
