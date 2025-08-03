from django.urls import path
from . import views

urlpatterns = [
    path('v1/', views.generate_proof, name='generate_proof'),
    path('jwks.json', views.jwks_view, name='jwks'),
] 