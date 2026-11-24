"""A task that outlives one reply.

Two approvals, neither of them the agent's: the person presses the store's
final button themselves in the live view, then approves the payment card
(payment_accounts.PaymentIntent). A task never orders and never pays.
"""
import uuid

from django.conf import settings
from django.db import models


class AgentProfile(models.Model):
    """A person's browser profile for one store (their sign-in there). Held by
    the vendor; here only its id. One per store, so one store's page can
    never reach another store's session."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_profiles')
    site = models.CharField(max_length=253)
    provider = models.CharField(max_length=32)
    external_id = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'site', 'provider'], name='agent_profile_uniq')]

    def __str__(self):
        return f'AgentProfile {self.pk} {self.site}'


class AgentCredential(models.Model):
    """A person's sign-in at one store, encrypted. Typed by the runner into the
    store's own sign-in page; never shown, logged, in the chat, or given to a model."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_credentials')
    site = models.CharField(max_length=253)
    secret = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'site'], name='agent_credential_one_per_store')]

    def __str__(self):
        return f'AgentCredential {self.pk} {self.site}'


class AgentTask(models.Model):
    STATES = [
        ('queued', 'Queued'),
        ('working', 'Working'),
        ('needs_person', 'Waiting for the person in the live view'),
        ('awaiting_code', 'The person finished the checkout: looking for its payment code'),
        ('payment_ready', 'Payment card posted'),
        ('stopped', 'Stopped'),
        ('cancelled', 'Cancelled'),
    ]
    ACTIVE = ('queued', 'working', 'needs_person', 'awaiting_code')
    # States in which a worker looks at the browser; in the others the person does, or nobody.
    RUNNING = ('queued', 'working', 'awaiting_code')

    internal_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    account = models.ForeignKey('users.Account', on_delete=models.PROTECT, related_name='agent_tasks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='agent_tasks')
    goal = models.TextField()  # the person's own words, verbatim
    site = models.CharField(max_length=253)
    country = models.CharField(max_length=2)  # where the store sells: its payment rail (countries.py)
    app_version = models.CharField(max_length=20, blank=True, default='')  # the build that started it

    state = models.CharField(max_length=20, choices=STATES, default='queued', db_index=True)
    reason = models.CharField(max_length=32, blank=True, default='')
    wait_until = models.DateTimeField(null=True, blank=True)
    # The checkout was handed to the person. Set once, never cleared: from
    # then on no model runs and nothing is pressed, typed or opened.
    checkout_at = models.DateTimeField(null=True, blank=True)
    # The one tab the person was shown: the only one a QR is read from.
    shown_target = models.CharField(max_length=64, blank=True, default='')
    # Hashes of every page the agent read: shopping pages, where a QR is a
    # seller's picture. An order's QR is on a page the person reached after.
    visited_pages = models.JSONField(default=list, blank=True)

    provider = models.CharField(max_length=32, blank=True, default='')
    session_id = models.CharField(max_length=128, blank=True, default='')
    # Controls a browser that may be signed in: never logged, shown or in the admin.
    connect_url = models.TextField(blank=True, default='')
    session_expires_at = models.DateTimeField(null=True, blank=True)

    lease = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    steps = models.PositiveSmallIntegerField(default=0)
    failures = models.PositiveSmallIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    # Short facts for the next step: what was done and what came of it. Never typed text.
    history = models.JSONField(default=list, blank=True)
    # The last pages the agent saw from the cart on, as the browser read them (their controls, a little text):
    # what a failure is diagnosed from, never guessed. Cleared with the rest (service.scrub).
    trace = models.JSONField(default=list, blank=True)

    # Products offered to the person in the chat: [{title, price, image, href}], what the
    # store's page showed (third-party text and pictures). They pick one; its page is opened next.
    options = models.JSONField(default=list, blank=True)
    pending_url = models.TextField(blank=True, default='')
    # The order the person is asked to approve: {item, total, button, image}. The total is the
    # store's own words; the agent presses the final button only for that same total.
    order = models.JSONField(default=dict, blank=True)
    # A one-time code the person typed for the store (encrypted, cleared when used).
    secret_once = models.TextField(blank=True, default='')
    # Where the purchase is: '' shopping, 'ordering' from the cart on, 'ordered' once the final
    # button was pressed. Kept here, not in the rolling history: safety checks read it.
    phase = models.CharField(max_length=12, blank=True, default='')
    # How many times each thing was tried or asked (sign-ins, asks, CAPTCHA waits, unread payments).
    counts = models.JSONField(default=dict, blank=True)

    payment_intent = models.ForeignKey('payment_accounts.PaymentIntent', on_delete=models.PROTECT,
                                       null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['user'], name='agent_task_one_active',
            condition=models.Q(state__in=('queued', 'working', 'needs_person', 'awaiting_code')))]
        indexes = [models.Index(fields=['user', 'created_at'], name='agent_task_user_idx')]

    def __str__(self):
        return f'AgentTask {self.internal_id} {self.state}'
