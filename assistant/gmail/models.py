"""Gmail pilot rows. Hard-deleted on purpose: disconnecting has to erase the token and what came from mail.

Everything that came from Google is sealed (crypto.seal): no mail is stored. The one row that outlives
a disconnect is GmailGrant, a keyed hash per Google account kept to mirror Google's lifetime count of 100.
"""
import uuid

from django.conf import settings
from django.db import models


class GmailConnection(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Conectado'
        EXPIRED = 'EXPIRED', 'Hay que reconectar'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='gmail_connection')
    # Changes on every connect: work started under an older grant writes nothing.
    grant = models.UUIDField(default=uuid.uuid4)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    sealed_token = models.TextField(blank=True, default='')
    sealed_email = models.TextField(blank=True, default='')
    email_key = models.CharField(max_length=64)
    can_send = models.BooleanField(default=False)
    consent_version = models.PositiveSmallIntegerField()
    connected_at = models.DateTimeField()
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(db_index=True)
    failures = models.PositiveSmallIntegerField(default=0)
    last_nudge_on = models.DateField(null=True, blank=True)
    # The one extra notice a day, for something due today that arrived after the first.
    last_urgent_on = models.DateField(null=True, blank=True)
    can_calendar = models.BooleanField(default=False)
    # The day the calendar was last counted for the notice. Nothing from the calendar is stored.
    calendar_checked_on = models.DateField(null=True, blank=True)

    class Meta:
        app_label = 'assistant'

    def __str__(self):
        return f'{self.user_id}: {self.status}'


class GmailGrant(models.Model):
    """A Google account that consented on Google's screen: Google counts it toward the 100 for life.

    Only a keyed hash (crypto.opaque) or a random key when the address was never learned. Kept on purpose
    after disconnecting or deleting the account: the count it mirrors is never reset.
    """

    key = models.CharField(max_length=64, unique=True)
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'assistant'


class GmailOAuthState(models.Model):
    """One connect attempt, bound to the person who started it."""

    state_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    challenge = models.CharField(max_length=64)
    consent_version = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        app_label = 'assistant'


class MailNeed(models.Model):
    class Kind(models.TextChoices):
        PAYMENT = 'payment', 'Pago'
        TICKET = 'ticket', 'Pasaje o entrada'
        TRIP = 'trip', 'Viaje'
        DEADLINE = 'deadline', 'Vencimiento'
        REPLY = 'reply', 'Correo por responder'
        APPOINTMENT = 'appointment', 'Cita o reunión'
        DELIVERY = 'delivery', 'Entrega'
        MONEY = 'money', 'Dinero recibido o por recibir'

    connection = models.ForeignKey(GmailConnection, on_delete=models.CASCADE, related_name='needs')
    source_key = models.CharField(max_length=64)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    due_date = models.DateField(null=True, blank=True)
    sealed = models.TextField()  # message id, amount, currency, one-line summary
    dismissed = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Follow-ups while it is still open (gmail.followups), as WhatsApp's notices.
    told_at = models.DateTimeField(null=True, blank=True)  # posted in her conversation (chat.tell); else never followed up
    followups = models.PositiveSmallIntegerField(default=0)
    followed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'assistant'
        constraints = [models.UniqueConstraint(fields=['connection', 'source_key'], name='mail_need_once')]


class MailDraft(models.Model):
    """An unsent draft: deleted when sent, or after 24 hours."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        SENDING = 'SENDING', 'Enviando'
        UNKNOWN = 'UNKNOWN', 'Resultado desconocido'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(GmailConnection, on_delete=models.CASCADE, related_name='drafts')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    sealed = models.TextField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        app_label = 'assistant'
