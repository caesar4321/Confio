"""The waitlist behind the paid-offer probes (Confío IA+, Cuenta inteligente).

Both offers are pure intent probes before launch: nothing is sold, charged or
unlocked. A row is the promise "te avisamos cuando esté" plus the person's
answers, one per person per product. Per-door numerators are computed from
these rows (door and trigger of the first join), never from client events,
which can fail silently. Design: docs/designs/cuenta-inteligente-fake-door.md.
"""
from django.conf import settings
from django.db import models

PRODUCT_IA_PLUS = 'ia_plus'
PRODUCT_SMART_ACCOUNT = 'smart_account'
PRODUCT_CHOICES = [
    (PRODUCT_IA_PLUS, 'Confío IA+'),
    (PRODUCT_SMART_ACCOUNT, 'Cuenta inteligente'),
]
PRODUCTS = frozenset(key for key, _ in PRODUCT_CHOICES)

# Where the pitch was opened from, and why.
DOORS = frozenset({'billeteras', 'assistant_header', 'chip'})
TRIGGERS = frozenset({'', 'investing', 'pain_point', 'model', 'asked'})
WOULD_PAY_CHOICES = [('yes', 'Sí'), ('no', 'No')]
VOLUME_RANGES = ('lt_100', '100_500', '500_2000', 'gt_2000')
VOLUME_CHOICES = [
    ('lt_100', '< US$100'),
    ('100_500', 'US$100–500'),
    ('500_2000', 'US$500–2.000'),
    ('gt_2000', '> US$2.000'),
]


class ProductWaitlistEntry(models.Model):
    """One person waiting for one paid offer. Unique per (user, product)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_waitlist_entries',
    )
    product = models.CharField(max_length=24, choices=PRODUCT_CHOICES)
    # Door and trigger of the FIRST join (a later visit doesn't move them).
    door = models.CharField(max_length=24)
    trigger = models.CharField(max_length=24, blank=True, default='')
    # Snapshot at join time, so the read needs no joins or guessing.
    account_type = models.CharField(max_length=16, blank=True, default='')
    funded = models.BooleanField(default=False)
    country = models.CharField(max_length=2, blank=True, default='')
    # "Si estuviera disponible hoy por US$X/mes, ¿te suscribirías?"
    would_pay = models.CharField(max_length=3, choices=WOULD_PAY_CHOICES, blank=True, default='')
    # Cuenta inteligente only: "¿Cuánto moverías o guardarías al mes en Confío?"
    volume_range = models.CharField(max_length=16, choices=VOLUME_CHOICES, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'product'], name='uniq_product_waitlist_user_product'),
        ]
        ordering = ['-created_at']
        verbose_name = 'Paid offer waitlist entry'
        verbose_name_plural = 'Paid offer waitlist entries'

    def __str__(self):
        return f'{self.user_id}: {self.product}'
