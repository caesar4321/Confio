from django.urls import path
from . import views

urlpatterns = [
    path('v1/', views.generate_proof, name='generate_proof'),
] 