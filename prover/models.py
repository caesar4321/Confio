from django.db import models
import uuid
from users.models import Account
from django.conf import settings
from django.contrib.auth import get_user_model

def generate_proof_id():
    return uuid.uuid4().hex

class ZkLoginProof(models.Model):
    proof_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_proof_id,
        editable=False
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="zk_proofs",
        help_text="Account for this specific zkLogin proof"
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
        return f"Proof {self.proof_id} for {self.account.account_id}"
