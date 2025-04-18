from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.utils import timezone
import uuid

User = get_user_model()

def generate_proof_id():
    return str(uuid.uuid4())

class ZkLoginProof(models.Model):
    proof_id = models.CharField(max_length=64, unique=True, default=generate_proof_id)
    jwt = models.TextField(null=True, blank=True)
    max_epoch = models.BigIntegerField(null=True, blank=True)
    randomness = models.BinaryField(null=True, blank=True)
    salt = models.BinaryField(null=True, blank=True)
    user_salt = models.BinaryField(null=True, blank=True)
    extended_ephemeral_public_key = models.BinaryField(null=True, blank=True)
    user_signature = models.BinaryField(null=True, blank=True)
    proof = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='zk_proofs', null=True)

    def __str__(self):
        return f"ZkLoginProof {self.proof_id}"

    class Meta:
        db_table = 'zk_login_proofs'

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', null=True)
    sui_address = models.CharField(max_length=128, unique=True, null=True, blank=True)
    user_salt = models.BinaryField(null=True, blank=True)
    google_sub = models.CharField(max_length=128, null=True, blank=True)
    apple_sub = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_login_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Profile for {self.user.username if self.user else 'Unknown'}"

    class Meta:
        db_table = 'user_profiles'
