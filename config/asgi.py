"""
ASGI entrypoint. Configures Django and then runs the application
defined in the ASGI_APPLICATION setting.
"""

import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from django.urls import path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from .consumers import MyGraphqlWsConsumer, MyGraphqlAppWsConsumer

application = ProtocolTypeRouter({
	'http': django_asgi_app,
	'websocket':
		AuthMiddlewareStack(
			URLRouter([
				path('graphql/', MyGraphqlWsConsumer.as_asgi()),
				path('graphqlapp/', MyGraphqlAppWsConsumer.as_asgi()),
			])
	),
})