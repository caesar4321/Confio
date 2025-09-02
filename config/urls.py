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
from django.views.generic.base import RedirectView
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

        # Derive account context from JWT, not from legacy request attributes
        try:
            from users.jwt_context import get_jwt_business_context_with_validation

            class FakeInfo:
                def __init__(self, ctx):
                    self.context = ctx

            jwt_ctx = get_jwt_business_context_with_validation(FakeInfo(context), required_permission=None)
            if jwt_ctx:
                context.active_account_type = jwt_ctx.get('account_type', 'personal')
                context.active_account_index = jwt_ctx.get('account_index', 0)
                context.active_business_id = jwt_ctx.get('business_id')
                # Mirror onto request for downstream logging that still reads request.*
                setattr(request, 'active_account_type', context.active_account_type)
                setattr(request, 'active_account_index', context.active_account_index)
                setattr(request, 'active_business_id', context.active_business_id)
            else:
                # Default to personal if no JWT context
                context.active_account_type = 'personal'
                context.active_account_index = 0
                context.active_business_id = None
        except Exception:
            # On any failure, keep safe defaults
            context.active_account_type = 'personal'
            context.active_account_index = 0
            context.active_business_id = None

        logger.info(f"GraphQL Context - User: {context.user}, Account Type: {context.active_account_type}, Account Index: {context.active_account_index}")

        return context
    
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            try:
                body = json.loads(request.body)
                query = body.get('query', '')
                logger.info("GraphQL Query: %s", query)
                logger.info("GraphQL Variables: %s", body.get('variables', {}))

                # Derive and align request account context from JWT prior to logging
                try:
                    from users.jwt_context import get_jwt_business_context_with_validation

                    class FakeInfo:
                        def __init__(self, ctx):
                            self.context = ctx

                    jwt_ctx = get_jwt_business_context_with_validation(FakeInfo(request), required_permission=None)
                    if jwt_ctx:
                        setattr(request, 'active_account_type', jwt_ctx.get('account_type', 'personal'))
                        setattr(request, 'active_account_index', jwt_ctx.get('account_index', 0))
                        setattr(request, 'active_business_id', jwt_ctx.get('business_id'))
                except Exception:
                    # Keep existing attributes if derivation fails
                    pass

                # Log aligned account context
                logger.info(
                    f"Request Account Context - Type: {getattr(request, 'active_account_type', 'not set')}, "
                    f"Index: {getattr(request, 'active_account_index', 'not set')}"
                )
                
                # Log balance queries specifically
                if 'accountBalance' in query:
                    logger.info(f"BALANCE QUERY DETECTED - User: {request.user}, Authenticated: {request.user.is_authenticated}")
                
                # Log conversion mutations specifically (informational)
                if 'convertUsdcToCusd' in query or 'convertCusdToUsdc' in query:
                    logger.info(f"CONVERSION MUTATION DETECTED - Query: {query[:200]}, Variables: {body.get('variables', {})}")
            except Exception as e:
                logger.error("Error parsing GraphQL request: %s", str(e))
        return super().dispatch(request, *args, **kwargs)

from .admin_dashboard import confio_admin_site

urlpatterns = [
    # Ensure /admin (no trailing slash) redirects to /admin/
    path('admin', RedirectView.as_view(url='/admin/', permanent=True)),
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
