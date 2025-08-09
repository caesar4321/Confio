"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
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
    def get_context(self, request):
        """Override to add account context to GraphQL context"""
        context = super().get_context(request)
        
        # Copy account context from request to GraphQL context
        context.active_account_type = getattr(request, 'active_account_type', 'personal')
        context.active_account_index = getattr(request, 'active_account_index', 0)
        context.active_business_id = getattr(request, 'active_business_id', None)
        
        logger.info(f"GraphQL Context - User: {context.user}, Account Type: {context.active_account_type}, Account Index: {context.active_account_index}")
        
        return context
    
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            try:
                body = json.loads(request.body)
                query = body.get('query', '')
                logger.info("GraphQL Query: %s", query)
                logger.info("GraphQL Variables: %s", body.get('variables', {}))
                
                # Log account context
                logger.info(f"Request Account Context - Type: {getattr(request, 'active_account_type', 'not set')}, Index: {getattr(request, 'active_account_index', 'not set')}")
                
                # Log balance queries specifically
                if 'accountBalance' in query:
                    logger.info(f"BALANCE QUERY DETECTED - User: {request.user}, Authenticated: {request.user.is_authenticated}")
                
                # Log conversion mutations specifically
                if 'convertUsdcToCusd' in query or 'convertCusdToUsdc' in query:
                    logger.error(f"CONVERSION MUTATION DETECTED - Query: {query[:200]}, Variables: {body.get('variables', {})}")
            except Exception as e:
                logger.error("Error parsing GraphQL request: %s", str(e))
        return super().dispatch(request, *args, **kwargs)

from .admin_dashboard import confio_admin_site

urlpatterns = [
    path('admin/', confio_admin_site.urls),
    path('graphql/', csrf_exempt(LoggingGraphQLView.as_view(graphiql=True))),
    path('terms/', terms_view, name='terms'),
    path('privacy/', privacy_view, name='privacy'),
    path('deletion/', deletion_view, name='deletion'),
]

# Add media files before catch-all pattern in DEBUG mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Import the index view
from .views import index

# Catch-all pattern should be last
urlpatterns += [
    re_path(r'^.*$', index),
]