from urllib.parse import parse_qs, urlparse

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class BillingCursorPagination(CursorPagination):
    cursor_query_param = 'starting_after'
    page_size = 50
    page_size_query_param = 'limit'
    max_page_size = 100
    ordering = ('-created_at', '-public_id')

    def get_paginated_response(self, data):
        next_link = self.get_next_link()
        cursor = None
        if next_link:
            cursor = parse_qs(urlparse(next_link).query).get(
                self.cursor_query_param, [None])[0]
        return Response({
            'data': data,
            'has_more': bool(next_link),
            'next_cursor': cursor,
        })
