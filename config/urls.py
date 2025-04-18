"""config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.views.decorators.csrf import csrf_exempt
from .views import DebugGraphQLView
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('admin/', admin.site.urls),
    path('graphql/', csrf_exempt(DebugGraphQLView.as_view(graphiql=True))),
    path('prover/', include('prover.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL)