"""The person's WhatsApp, linked as a device in a browser that is theirs alone.

Hard-deleted on purpose: unlinking erases the browser profile at the vendor,
the important messages kept and the drafts. Everything that came from
WhatsApp is sealed (users.encryption); only fixed kinds and times are plain.
"""
import uuid

from django.conf import settings
from django.db import models


class WhatsAppLink(models.Model):
    class State(models.TextChoices):
        PAIRING = 'pairing', 'Esperando el código'
        LINKED = 'linked', 'Vinculado'
        GONE = 'gone', 'Desvinculado desde el teléfono'
        FAILED = 'failed', 'No se pudo vincular'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='whatsapp_link')
    # Changes on every pairing: work started under an older one writes nothing.
    grant = models.UUIDField(default=uuid.uuid4)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PAIRING, db_index=True)
    reason = models.CharField(max_length=24, blank=True, default='')

    # The person's browser profile at the vendor: their WhatsApp session. Never shared.
    provider = models.CharField(max_length=32)
    context_id = models.CharField(max_length=128, blank=True, default='')
    session_id = models.CharField(max_length=128, blank=True, default='')
    # Controls a browser signed in to the person's WhatsApp: sealed, never logged or shown.
    sealed_connect_url = models.TextField(blank=True, default='')
    session_expires_at = models.DateTimeField(null=True, blank=True)

    sealed_phone = models.TextField(blank=True, default='')
    phone_hint = models.CharField(max_length=4, blank=True, default='')  # last digits, for the screen
    phone_key = models.CharField(max_length=64, blank=True, default='')  # HMAC of the whole number linked
    sealed_code = models.TextField(blank=True, default='')
    code_at = models.DateTimeField(null=True, blank=True)

    # The version of the text the person accepted before linking (service.CONSENT_VERSION).
    consent_version = models.PositiveSmallIntegerField(default=0)
    linked_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'WhatsAppLink {self.pk} {self.state}'


class WhatsAppNotice(models.Model):
    """An unread message the classifier found important. Only the chat's
    name, the list's one-line preview and a fixed kind: the chat is never opened to read it."""

    class Kind(models.TextChoices):
        PAYMENT = 'payment', 'Cobro o pago'
        ORDER = 'order', 'Pedido'
        DELIVERY = 'delivery', 'Entrega'
        APPOINTMENT = 'appointment', 'Cita'
        REPLY = 'reply', 'Te escribieron y esperan respuesta'
        URGENT = 'urgent', 'Urgente'

    link = models.ForeignKey(WhatsAppLink, on_delete=models.CASCADE, related_name='notices')
    source_key = models.CharField(max_length=64)  # an HMAC of chat + preview: dedupe without the text
    kind = models.CharField(max_length=12, choices=Kind.choices)
    sealed = models.TextField()  # {chat, preview, summary, time}
    dismissed = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['link', 'source_key'], name='whatsapp_notice_once')]


class WhatsAppDraft(models.Model):
    """A message the person may send from their WhatsApp. Sent only when they
    tap Enviar on exactly this text; deleted when sent or after 24 hours."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Borrador'
        SENDING = 'sending', 'Enviando'
        SENT = 'sent', 'Enviado'
        UNKNOWN = 'unknown', 'Resultado desconocido'
        FAILED = 'failed', 'No se envió'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    link = models.ForeignKey(WhatsAppLink, on_delete=models.CASCADE, related_name='drafts')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    reason = models.CharField(max_length=24, blank=True, default='')
    sealed = models.TextField()  # {chat, phone, body}
    expires_at = models.DateTimeField(db_index=True)
    sending_at = models.DateTimeField(null=True, blank=True)  # the tap: a send silent past minutes is unknown
    created_at = models.DateTimeField(auto_now_add=True)
