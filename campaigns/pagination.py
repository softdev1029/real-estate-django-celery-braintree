from rest_framework.pagination import CursorPagination


class BatchProspectsPagination(CursorPagination):
    """
    Cursor pagination for the batch prospects.

    The issue with default PageNumberPagination here is that when we fetch the next page of results
    we need to get the results starting from where the first page left off. When we use the page
    number pagination, when we send 50 prospects and then fetch page 2, the results will be
    prospects #151-#251 instead of #101-200, and those 50 prospects are left out of the sending
    process.

    By switching to CursorPagination, the 2nd page will begin with prospect #101 instead of basing
    the second page's starting position off of where the user is currently at.
    """
    ordering = ('created_date',)
