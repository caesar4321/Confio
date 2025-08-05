from django.urls import path
from .web_oauth_views import AptosOAuthStartView, AptosOAuthCallbackView, AptosOAuthSuccessView, AptosOAuthCloseView

urlpatterns = [
    path('oauth/aptos/start/', AptosOAuthStartView.as_view(), name='aptos_oauth_start'),
    path('oauth/aptos/callback/', AptosOAuthCallbackView.as_view(), name='aptos_oauth_callback'),
    path('oauth/aptos/success/', AptosOAuthSuccessView.as_view(), name='aptos_oauth_success'),
    path('oauth/aptos/close/', AptosOAuthCloseView.as_view(), name='aptos_oauth_close'),
]