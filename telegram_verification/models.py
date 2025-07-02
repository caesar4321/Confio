from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel

class TelegramVerification(SoftDeleteModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=20)
    request_id = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    
    class Meta:
        indexes = [
            models.Index(fields=['phone_number', 'request_id']),
            models.Index(fields=['user']),
        ]
