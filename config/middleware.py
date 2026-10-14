from django.db import close_old_connections


class CloseDbConnectionsMiddleware:
    """
    Ensures Django drops any stale DB connections at the start of each request.
    With the DB_POOL connection pool this hands a broken or unusable
    connection back to the pool instead of reusing it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        close_old_connections()
        response = self.get_response(request)
        return response

