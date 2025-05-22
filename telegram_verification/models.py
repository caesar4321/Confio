from django.db import models
from django.conf import settings

class TelegramVerification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20)
    request_id = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['phone_number', 'request_id']),
            models.Index(fields=['user']),
        ]
