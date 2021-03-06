import time

from django.conf import settings


class TimeDelayMiddleware(object):
    """
    Set a delay for API requests giving a more realistic frontend development experience.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.delay = settings.REQUEST_TIME_DELAY

    def __call__(self, request):
        if '/api/' in request.path and self.delay > 0:
            time.sleep(self.delay)
        response = self.get_response(request)
        return response
