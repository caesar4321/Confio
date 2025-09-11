"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import OriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from p2p_exchange.routing import websocket_urlpatterns
from p2p_exchange.middleware import JWTAuthMiddleware

# Allowed origins for WebSocket connections (explicit list avoids 403 on valid clients)
allowed_ws_origins = [
    "https://confio.lat",
    "https://www.confio.lat",
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": OriginValidator(
        JWTAuthMiddleware(
            URLRouter(websocket_urlpatterns)
        ),
        allowed_ws_origins
    ),
})
