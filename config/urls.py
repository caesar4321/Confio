"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from .views import index
from .sitemaps import StaticViewSitemap, LocalizationSitemap
from django.contrib.sitemaps.views import sitemap
from graphene_django.views import GraphQLView
from django.conf.urls.static import static
from django.conf import settings
from django.views.decorators.clickjacking import xframe_options_exempt

sitemaps = {
    'static': StaticViewSitemap,
    'localization': LocalizationSitemap,
}

urlpatterns = [
    path('', ensure_csrf_cookie(index)),
    re_path(r'^[a-z]{2}/$', ensure_csrf_cookie(index)),
    path('index.html', ensure_csrf_cookie(index)),
    path('login/', ensure_csrf_cookie(index)),
    path('terms_of_service/', ensure_csrf_cookie(index), name='terms_of_service'),
    path('privacy_policy/', ensure_csrf_cookie(index), name='privacy_policy'),
    path('frequently_asked_questions/', ensure_csrf_cookie(index), name='frequently_asked_questions'),
    path('whitepaper/', ensure_csrf_cookie(index), name='whitepaper'),
    path('career/programmer/', ensure_csrf_cookie(index), name='career/programmer'),
    path('career/content_creator', ensure_csrf_cookie(index), name='career/content_creator'),
    re_path(r'^[a-z]{2}/terms_of_service/$', ensure_csrf_cookie(index)),
    re_path(r'^[a-z]{2}/privacy_policy/$', ensure_csrf_cookie(index)),
    re_path(r'^[a-z]{2}/frequently_asked_questions/$', ensure_csrf_cookie(index)),
    
    path('accounts/confio_manager/', admin.site.urls),

    path('sitemap.xml', sitemap, {'sitemaps': sitemaps},
        name='django.contrib.sitemaps.views.sitemap')

]

if settings.DEBUG:
    urlpatterns += [
        path('graphql/', csrf_exempt(GraphQLView.as_view(graphiql=True))),
        path('graphqlapp/', csrf_exempt(GraphQLView.as_view(graphiql=True))),
    ] + static(settings.STATIC_URL)
else:
    urlpatterns += [
    path('graphql/', GraphQLView.as_view(graphiql=False)),
    path('graphqlapp/', csrf_exempt(GraphQLView.as_view(graphiql=False))),
]