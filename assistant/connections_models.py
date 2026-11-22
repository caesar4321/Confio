"""Who asked for, and who holds, a place to connect mail or calendar."""
from django.conf import settings
from django.db import models


class AssistantConnectionRequest(models.Model):
    """One per person and feature.

    Gmail, by hand: reserved (invited_at, the address freezes), added in
    Google's console, then given (ready_at: only now is there access). ready_at
    is never cleared: it is the only proof the address is in Google's console.

    A Gmail place, once given, is spent for good: Google's 100 test users are
    a lifetime count per project. So removing someone keeps invited_at, and
    deleting the person keeps the row (user = NULL).
    """

    class Feature(models.TextChoices):
        GMAIL = 'gmail', 'Gmail'
        CALENDAR = 'calendar', 'Calendario'

    class Answer(models.TextChoices):
        YES = 'yes', 'Sí, avísame'
        NO = 'no', 'Solo miraba'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                             related_name='assistant_connection_requests')
    feature = models.CharField(max_length=16, choices=Feature.choices)
    answer = models.CharField(max_length=4, choices=Answer.choices)
    # The Google account to add as a test user, as they typed it. Never guessed from the sign-in.
    google_email = models.CharField(max_length=254, blank=True, default='')
    asked_at = models.DateTimeField(auto_now_add=True)
    invited_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'assistant'
        constraints = [models.UniqueConstraint(fields=['user', 'feature'], name='assistant_connection_once')]
        indexes = [models.Index(fields=['feature', 'answer', 'asked_at'], name='assistant_connection_queue')]

    def __str__(self):
        return f'{self.feature}: {self.user_id} ({self.answer})'
