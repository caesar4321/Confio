"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.decorators.csrf import csrf_exempt
from django.contrib.admin.views.decorators import staff_member_required
from graphene_django.views import GraphQLView
from .views import (
    terms_view,
    privacy_view,
    deletion_view,
    entity_page,
    robots_txt,
    llms_txt,
    public_sitemap,
    portal_login_complete,
    portal_login_redirect,
    portal_logout,
    portal_setup_2fa_redirect,
)
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from two_factor.urls import urlpatterns as tf_urls
import json
import logging

# Customize admin site
admin.site.site_header = "Confío Admin"
admin.site.site_title = "Confío Admin Portal"
admin.site.index_title = "Welcome to Confío Administration"

logger = logging.getLogger(__name__)


def _should_log_graphql_request_details():
    return settings.DEBUG

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

        if _should_log_graphql_request_details():
            logger.info(
                "GraphQL Context - User: %s, Account Type: %s, Account Index: %s",
                context.user,
                context.active_account_type,
                context.active_account_index,
            )

        return context
    
    def dispatch(self, request, *args, **kwargs):
        if request.method == 'POST':
            try:
                body = json.loads(request.body)
                query = body.get('query', '')
                if _should_log_graphql_request_details():
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
                if _should_log_graphql_request_details():
                    logger.info(
                        "Request Account Context - Type: %s, Index: %s",
                        getattr(request, 'active_account_type', 'not set'),
                        getattr(request, 'active_account_index', 'not set'),
                    )
                
                # Log balance queries specifically
                if settings.DEBUG and 'accountBalance' in query:
                    logger.info(
                        "BALANCE QUERY DETECTED - User: %s, Authenticated: %s",
                        request.user,
                        request.user.is_authenticated,
                    )
                
                # Log conversion mutations specifically (informational)
                if settings.DEBUG and (
                    'convertUsdcToCusd' in query or 'convertCusdToUsdc' in query
                ):
                    logger.info(
                        "CONVERSION MUTATION DETECTED - Query: %s, Variables: %s",
                        query[:200],
                        body.get('variables', {}),
                    )
            except Exception as e:
                logger.error("Error parsing GraphQL request: %s", str(e))
        return super().dispatch(request, *args, **kwargs)

from .admin_dashboard import confio_admin_site
from config.sitemaps import StaticPageSitemap
from inbox.feeds import DiscoverFeed
from inbox.views import discover_feed, discover_post_detail
from inbox.sitemaps import DiscoverSitemap

sitemaps = {
    'static': StaticPageSitemap,
    'discover': DiscoverSitemap,
}

urlpatterns = [
    # Ensure /admin (no trailing slash) redirects to /admin/
    # path('admin', RedirectView.as_view(url='/admin/', permanent=True)), # Disabled for security obfuscation
    path('', include(tf_urls)),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('llms.txt', llms_txt, name='llms_txt'),
    path('sitemap.xml', public_sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('confio-control-panel/', confio_admin_site.urls),
    path('graphql/', csrf_exempt(LoggingGraphQLView.as_view(graphiql=True))),
    path('portal/login/', portal_login_redirect, name='portal_login'),
    path('portal/login-complete/', portal_login_complete, name='portal_login_complete'),
    path('portal/logout/', portal_logout, name='portal_logout'),
    path('portal/setup-2fa/', portal_setup_2fa_redirect, name='portal_setup_2fa'),
    path('discover/feed.xml', DiscoverFeed(), name='discover_feed_xml'),
    re_path(r'^discover/?$', discover_feed, name='discover_feed'),
    re_path(r'^discover/(?P<post_id>\d+)/(?P<slug>[-\w]+)/?$', discover_post_detail, name='discover_post_detail'),
    re_path(r'^discover/(?P<post_id>\d+)/?$', discover_post_detail, name='discover_post_detail_no_slug'),
    re_path(r'^about/(?P<entity_slug>julian-moon|confio-news)/?$', entity_page, name='entity_page'),
    path('faq/', RedirectView.as_view(url='/about/confio-news', permanent=True)),
    path('faq', RedirectView.as_view(url='/about/confio-news', permanent=True)),
    re_path(r'^terms/?$', terms_view, name='terms'),
    re_path(r'^privacy/?$', privacy_view, name='privacy'),
    re_path(r'^deletion/?$', deletion_view, name='deletion'),
]

# Add media files before catch-all pattern in DEBUG mode
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Import the index view
from .views import index
from .views import guardarian_transaction_proxy, guardarian_fiat_currencies
from ramps.views import koywe_webhook
from security.views import didit_webhook
from users.funnel_ingest import funnel_ingest

# Catch-all pattern should be last
urlpatterns += [
    path('api/didit/webhook/', didit_webhook, name='didit_webhook'),
    path('api/koywe/webhook/', koywe_webhook, name='koywe_webhook'),
    path('api/funnel/ingest/', funnel_ingest, name='funnel_ingest'),
    path('api/guardarian/fiat/', guardarian_fiat_currencies, name='guardarian_fiat_currencies'),
    path('api/guardarian/transaction/', guardarian_transaction_proxy, name='guardarian_transaction_proxy'),
    re_path(r'^.*$', index),
]
