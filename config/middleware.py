from django.db import close_old_connections


class CloseDbConnectionsMiddleware:
    """
    Ensures Django drops any stale DB connections at the start of each request.
    This is important when using a pooler (e.g., RDS Proxy), where backend
    connections can be closed between requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        close_old_connections()
        response = self.get_response(request)
        return response

