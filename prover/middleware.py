"""
Middleware for handling ngrok interstitial bypass
"""
from django.utils.deprecation import MiddlewareMixin

class NgrokMiddleware(MiddlewareMixin):
    """Add ngrok-skip-browser-warning header to all responses"""
    
    def process_response(self, request, response):
        # Add header to skip ngrok warning page
        if 'ngrok' in request.get_host():
            response['ngrok-skip-browser-warning'] = 'true'
        return response