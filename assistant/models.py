"""Confio Assistant: the customer assistant that answers in the support thread.

Conversation text lives in inbox.SupportMessage (one history for typed text,
voice notes, realtime transcripts and staff replies). This app only keeps what
the assistant itself needs: per-user preferences, the AI/human mode of a
thread, and a metered record of every model turn.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Mascot(models.TextChoices):
    CONFI = 'CONFI', 'Confi'
    LLAMA = 'LLAMA', 'Llama'
    CAPYBARA = 'CAPYBARA', 'Capibara'
    CAT = 'CAT', 'Gato'
    DOG = 'DOG', 'Perro'
    CUSTOM = 'CUSTOM', 'Personaje creado por el usuario'


class AssistantProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_profile')
    mascot = models.CharField(max_length=16, choices=Mascot.choices, default=Mascot.CONFI)
    # What the user calls their pet; the assistant still introduces itself as Confio Assistant.
    mascot_name = models.CharField(max_length=24, blank=True, default='')
    mascot_color = models.CharField(max_length=7, blank=True, default='')
    bubble_hidden = models.BooleanField(default=False)
    # Bubble position, remembered per user: 'right' or 'left' edge, and how
    # far up the screen (0 = bottom, 1 = top).
    bubble_side = models.CharField(max_length=5, default='right')
    bubble_height = models.FloatField(default=0.0)
    wake_word_enabled = models.BooleanField(default=False)
    # Opaque id the stores carry with every purchase (Apple appAccountToken,
    # Google obfuscatedAccountId): binds a store subscription to this user
    # without sharing who they are. Assigned on first use.
    billing_token = models.UUIDField(null=True, blank=True, unique=True)
    # The pet the user created, when mascot == CUSTOM.
    custom_pet = models.ForeignKey('assistant.CustomPet', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.user_id}: {self.mascot}'


class AssistantThreadState(models.Model):
    """Who answers a support thread: Confio Assistant, or the human team after a handoff.

    Human mode is never permanent: it lapses on its own once the team has been
    quiet for CONFIO_ASSISTANT_HUMAN_MODE_HOURS, so a user is never left waiting on a
    flag nobody clears.
    """
    conversation = models.OneToOneField(
        'inbox.SupportConversation', on_delete=models.CASCADE, related_name='assistant_state',
    )
    handoff_at = models.DateTimeField(null=True, blank=True)
    handoff_reason = models.CharField(max_length=280, blank=True, default='')
    returned_to_ai_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class TurnModality(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    VOICE_NOTE = 'VOICE_NOTE', 'Voice note'
    REALTIME = 'REALTIME', 'Realtime voice'


class AssistantTurn(models.Model):
    """One metered assistant reply: model, tokens, cost, tools and actions."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_turns')
    conversation = models.ForeignKey(
        'inbox.SupportConversation', on_delete=models.CASCADE, related_name='assistant_turns',
    )
    user_message = models.ForeignKey(
        'inbox.SupportMessage', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    reply_message = models.ForeignKey(
        'inbox.SupportMessage', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    modality = models.CharField(max_length=16, choices=TurnModality.choices, default=TurnModality.TEXT)
    screen = models.CharField(max_length=64, blank=True, default='')
    models_used = models.JSONField(default=list, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    cached_input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    audio_seconds = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    tools = models.JSONField(default=list, blank=True)
    actions = models.JSONField(default=list, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=280, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', '-created_at'], name='assistant_turn_user_idx'),
            models.Index(fields=['-created_at'], name='assistant_turn_created_idx'),
        ]


class SubscriptionStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    GRACE = 'GRACE', 'Grace period (billing retry, still entitled)'
    ON_HOLD = 'ON_HOLD', 'On hold (payment failed, not entitled)'
    PENDING = 'PENDING', 'Pending payment'
    EXPIRED = 'EXPIRED', 'Expired'
    REVOKED = 'REVOKED', 'Refunded / revoked'


ENTITLED_STATUSES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE)


class AssistantSubscription(models.Model):
    """One store subscription (Assistant+), as last verified with Apple or Google.

    store_key is the stable store identity: Apple originalTransactionId, or
    the Google purchase token (a resubscribe gets a new token; the old one is
    marked superseded via linked_purchase_token).
    """
    PLATFORMS = [('ios', 'App Store'), ('android', 'Google Play')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_subscriptions')
    platform = models.CharField(max_length=8, choices=PLATFORMS)
    store_key = models.CharField(max_length=512)
    product_id = models.CharField(max_length=128)
    status = models.CharField(max_length=10, choices=SubscriptionStatus.choices)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Entitlement continues to this time while the store retries payment.
    grace_until = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    environment = models.CharField(max_length=16, blank=True, default='')
    latest_transaction_id = models.CharField(max_length=128, blank=True, default='')
    acknowledged = models.BooleanField(default=False)
    # Store signedDate (ms) of the last applied transaction: older payloads
    # (a replayed purchase, a late notification) must never undo newer state.
    last_signed_ms = models.BigIntegerField(null=True, blank=True)
    superseded_by = models.CharField(max_length=512, blank=True, default='')
    last_payload = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['platform', 'store_key'], name='assistant_sub_store_key_uniq'),
        ]
        indexes = [models.Index(fields=['user', 'status'], name='assistant_sub_user_idx')]

    def is_entitled(self, now=None):
        now = now or timezone.now()
        if self.superseded_by or self.status not in ENTITLED_STATUSES:
            return False
        until = max(t for t in (self.expires_at, self.grace_until) if t) if (self.expires_at or self.grace_until) else None
        return until is not None and until > now


class StoreNotification(models.Model):
    """Every store server notification, deduplicated, for audit and replay."""
    platform = models.CharField(max_length=8)
    notification_id = models.CharField(max_length=128)
    notification_type = models.CharField(max_length=64, blank=True, default='')
    store_key = models.CharField(max_length=512, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    error = models.CharField(max_length=280, blank=True, default='')
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['platform', 'notification_id'], name='assistant_store_notif_uniq'),
        ]


class VoiceSession(models.Model):
    """One realtime voice call (Assistant+). Duration is measured by the server
    (started_at → last_seen_at), never taken from the client."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_voice_sessions')
    conversation = models.ForeignKey('inbox.SupportConversation', on_delete=models.CASCADE, related_name='+')
    # The JWT account the call was started from; every tool call must match.
    account_id = models.BigIntegerField(null=True, blank=True)
    business_id = models.BigIntegerField(null=True, blank=True)
    # OpenAI call id (from the SDP answer's Location), so the server can hang up.
    call_id = models.CharField(max_length=128, blank=True, default='')
    # True once OpenAI confirmed the hangup (or the call never connected);
    # the sweeper retries ended calls until then.
    remote_ended = models.BooleanField(default=False)
    model = models.CharField(max_length=64)
    screen = models.CharField(max_length=64, blank=True, default='')
    tz_name = models.CharField(max_length=64, blank=True, default='')
    started_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    # Usage the client relays from response.done events (for cost reporting
    # only; minutes are enforced from server timestamps).
    usage = models.JSONField(default=dict, blank=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    tools = models.JSONField(default=list, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-started_at'], name='assistant_voice_user_idx')]

    @property
    def seconds(self):
        end = self.ended_at or self.last_seen_at
        return max((end - self.started_at).total_seconds(), 0)


class CustomPet(models.Model):
    """A pet the user created from an idea or a photo of their own pet.

    Private to the user (never shown to anyone else). The image lives in the
    private bucket and is served through short-lived signed URLs.
    """
    SOURCES = [('idea', 'Idea'), ('photo', 'Photo')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_pets')
    source = models.CharField(max_length=8, choices=SOURCES)
    idea = models.CharField(max_length=300, blank=True, default='')
    image_key = models.CharField(max_length=512)
    model = models.CharField(max_length=64)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', '-created_at'], name='assistant_pet_user_idx')]


class ProbeAnswer(models.Model):
    """One tap answer to a server-defined question the bubble asked once
    ("¿Para qué te gustaría usar Confío?"). Evidence for product decisions;
    never shown to other users."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_probe_answers')
    probe_id = models.CharField(max_length=64)
    answer = models.CharField(max_length=32)
    # Snapshot at answer time, so later analysis needs no joins or guessing.
    phone_country = models.CharField(max_length=2, blank=True, default='')
    funded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'probe_id'], name='assistant_probe_once_per_user')]
        indexes = [models.Index(fields=['probe_id', 'answer'], name='assistant_probe_answer_idx')]

    def __str__(self):
        return f'{self.probe_id}: {self.answer}'
