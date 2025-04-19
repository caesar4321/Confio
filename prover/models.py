from django.db import models
import uuid
from users.models import UserProfile
from django.conf import settings
from django.contrib.auth import get_user_model

def generate_proof_id():
    return uuid.uuid4().hex

class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='zk_profile'
    )
    google_sub = models.CharField(max_length=255, null=True, blank=True)
    apple_sub = models.CharField(max_length=255, null=True, blank=True)
    sui_address = models.CharField(max_length=255, null=True, blank=True)
    user_salt = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.user)

class ZkLoginProof(models.Model):
    proof_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_proof_id,
        editable=False
    )
    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="zk_proofs",
    )

    # —————————————————————————————
    # per‑proof inputs
    # —————————————————————————————
    max_epoch = models.PositiveIntegerField()
    randomness = models.BinaryField()
    extended_ephemeral_public_key = models.BinaryField()
    user_signature = models.BinaryField()

    # —————————————————————————————
    # per‑proof output
    # —————————————————————————————
    proof_data = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Proof {self.proof_id} for {self.profile.user}"
