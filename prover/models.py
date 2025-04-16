from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class ZkLoginProof(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='zk_login_proofs')
    jwt = models.TextField(help_text="The JWT token to be proven")
    max_epoch = models.IntegerField(help_text="Maximum epoch for which the proof is valid")
    randomness = models.CharField(max_length=255, help_text="Randomness used in proof generation")
    salt = models.CharField(max_length=255, help_text="Salt used in proof generation")
    proof_data = models.JSONField(help_text="The actual zkLogin proof data")
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['is_verified']),
        ]

    def __str__(self):
        return f"ZkLoginProof for {self.user.email} at {self.created_at}"
