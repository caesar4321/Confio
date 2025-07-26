"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView
from .views import terms_view, privacy_view, deletion_view
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
import json
import logging

# Customize admin site
admin.site.site_header = "Confío Admin"
admin.site.site_title = "Confío Admin Portal"
admin.site.index_title = "Welcome to Confío Administration"

logger = logging.getLogger(__name__)

class LoggingGraphQLView(GraphQLView):
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            try:
                body = json.loads(request.body)
                query = body.get('query', '')
                logger.info("GraphQL Query: %s", query)
                logger.info("GraphQL Variables: %s", body.get('variables', {}))
                
                # Log balance queries specifically
                if 'accountBalance' in query:
                    logger.info(f"BALANCE QUERY DETECTED - User: {request.user}, Authenticated: {request.user.is_authenticated}")
            except Exception as e:
                logger.error("Error parsing GraphQL request: %s", str(e))
        return super().dispatch(request, *args, **kwargs)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('graphql/', csrf_exempt(LoggingGraphQLView.as_view(graphiql=True))),
    path('prover/', include('prover.urls')),
    re_path(r'^.*$', TemplateView.as_view(template_name='index.html')),
    path('terms/', terms_view, name='terms'),
    path('privacy/', privacy_view, name='privacy'),
    path('deletion/', deletion_view, name='deletion'),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT) + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)