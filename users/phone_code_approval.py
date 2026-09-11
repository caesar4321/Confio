"""Recover an approved OTP after a lost confirmation-preview response."""
import json

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac


def _code_hash(proof, code):
    value = json.dumps([proof._meta.label_lower, proof.pk, proof.user_id,
                        proof.phone_number, code], separators=(',', ':'))
    return salted_hmac('users.phone-code-approval.v1', value,
                       algorithm='sha256').hexdigest()


def _active_proof(proof):
    current = type(proof).objects.select_for_update().filter(pk=proof.pk).first()
    if (current is None or current.user_id != proof.user_id
            or current.phone_number != proof.phone_number
            or current.is_verified or current.expires_at <= timezone.now()):
        return None
    return current


def cached_code_approval(proof, code):
    """Return None before approval, otherwise validate the bounded cached OTP."""
    with transaction.atomic():
        current = _active_proof(proof)
        if current is None:
            return False
        if not current.approved_code_hash:
            return None
        if current.attempts >= 5:
            return False
        if constant_time_compare(current.approved_code_hash, _code_hash(current, code)):
            return True
        type(proof).objects.filter(pk=current.pk).update(attempts=F('attempts') + 1)
        return False


def record_code_approval(proof, code):
    """Persist provider approval independently of the link/preview transaction."""
    with transaction.atomic():
        current = _active_proof(proof)
        if current is None or current.attempts >= 5:
            return False
        digest = _code_hash(current, code)
        if current.approved_code_hash:
            return constant_time_compare(current.approved_code_hash, digest)
        current.approved_code_hash = digest
        current.save(update_fields=['approved_code_hash'])
        return True
