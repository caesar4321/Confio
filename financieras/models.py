"""
Financieras directory models.

Confío does NOT intermediate these exchanges. We only list local financieras
(casas de cambio) with their WhatsApp, location and community ratings so users
can convert USDC to physical USD cash with a counterparty they can verify and,
if they want, visit in person.

Key invariants:
- Registration requires the owner to have completed identity verification and
  to commit to accepting USDC over the Algorand network (the only rail at
  launch).
- The exchange rate is never registered by the financiera. It is derived from
  what verified users report in reviews ("envié 100 USDC, recibí $98").
- Reviews are shown anonymously; the reviewer FK exists only for moderation
  and rate-limiting, and must never be exposed through the API.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import models
from django.db.models import Avg, Count, F

from users.country_codes import COUNTRY_CODES
from users.models import SoftDeleteModel


COUNTRY_CHOICES = [(code[2], f"{code[0]} ({code[1]})") for code in COUNTRY_CODES]

# Digits-only E.164 without the leading '+', e.g. '584141234567'
whatsapp_validator = RegexValidator(
    regex=r'^\d{8,15}$',
    message='WhatsApp number must be 8-15 digits (country code included, no +)',
)


class FinancieraQuerySet(models.QuerySet):
    def with_stats(self):
        """Annotate listing stats so the directory can sort without N+1."""
        return self.annotate(
            annotated_avg_rating=Avg(
                'reviews__rating', filter=models.Q(reviews__deleted_at__isnull=True)
            ),
            annotated_review_count=Count(
                'reviews', filter=models.Q(reviews__deleted_at__isnull=True)
            ),
            annotated_avg_ratio=Avg(
                F('reviews__received_usd') / F('reviews__sent_usdc'),
                filter=models.Q(reviews__deleted_at__isnull=True),
            ),
        )

    def visible(self):
        return self.filter(deleted_at__isnull=True, is_active=True)


class Financiera(SoftDeleteModel):
    """A local money exchange business listed in the directory."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='financieras',
        help_text='Identity-verified user who registered this financiera',
    )
    name = models.CharField(max_length=100)

    # Location (free text below country level; backed by review data, not geo APIs)
    country_code = models.CharField(
        max_length=2,
        choices=COUNTRY_CHOICES,
        db_index=True,
        help_text='ISO country code, e.g. VE, AR',
    )
    state = models.CharField(max_length=100, help_text='Estado / provincia')
    city = models.CharField(max_length=100)
    neighborhood = models.CharField(
        max_length=120, blank=True, default='', help_text='Barrio / zona'
    )

    whatsapp = models.CharField(
        max_length=15,
        validators=[whatsapp_validator],
        help_text='Digits-only E.164 without +, e.g. 584141234567',
    )

    # Services. Supporting USDC over Algorand is mandatory to be listed — the
    # only rail at launch. Kept as a column (not implied) so the requirement is
    # explicit, auditable, and future rails can be added alongside it.
    supports_usdc_algorand = models.BooleanField(
        default=False,
        help_text='Mandatory: accepts USDC over the Algorand network',
    )
    helps_with_confio = models.BooleanField(
        default=False, help_text='Helps newcomers use the Confío app'
    )
    home_service = models.BooleanField(
        default=False, help_text='Offers home/office delivery (a domicilio)'
    )
    open_weekends = models.BooleanField(default=False)

    is_active = models.BooleanField(
        default=True,
        help_text='Unlisted from the directory when False (moderation switch)',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = FinancieraQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['country_code', 'state', 'city']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['owner', 'name', 'city'],
                condition=models.Q(deleted_at__isnull=True),
                name='unique_active_financiera_per_owner_name_city',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}, {self.country_code})'

    @property
    def is_verified(self):
        """Re-checked at read time in case the owner's verification is revoked."""
        return self.owner.is_identity_verified

    @property
    def avg_rating(self):
        annotated = getattr(self, 'annotated_avg_rating', None)
        if annotated is not None:
            return float(annotated)
        return self.reviews.aggregate(v=Avg('rating'))['v']

    @property
    def review_count(self):
        annotated = getattr(self, 'annotated_review_count', None)
        if annotated is not None:
            return annotated
        return self.reviews.count()

    @property
    def avg_received_per_100(self):
        """Average USD received per 100 USDC sent, from reviews ("100 USDC → $98")."""
        ratio = getattr(self, 'annotated_avg_ratio', None)
        if ratio is None:
            ratio = self.reviews.aggregate(
                v=Avg(F('received_usd') / F('sent_usdc'))
            )['v']
        if ratio is None:
            return None
        return round(float(ratio) * 100, 1)


class FinancieraReview(SoftDeleteModel):
    """Anonymous review by an identity-verified user, anchored to a real
    USDC-Algorand transaction.

    Every review must reference exactly one confirmed USDC outflow owned by the
    reviewer — either a Confío send or an external withdrawal — and each
    transaction can back at most one review. sent_usdc is copied from the
    transaction server-side, never taken from the client, so the directory's
    derived rates reflect money that actually moved. The reviewer is kept for
    moderation/rate-limiting but never exposed.
    """

    financiera = models.ForeignKey(
        Financiera, on_delete=models.CASCADE, related_name='reviews'
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='financiera_reviews',
        help_text='Kept for moderation and rate-limiting; never exposed via API',
    )
    send_transaction = models.ForeignKey(
        'send.SendTransaction',
        on_delete=models.PROTECT,
        related_name='financiera_reviews',
        null=True,
        blank=True,
        help_text='Confirmed USDC send backing this review (XOR usdc_withdrawal)',
    )
    usdc_withdrawal = models.ForeignKey(
        'usdc_transactions.USDCWithdrawal',
        on_delete=models.PROTECT,
        related_name='financiera_reviews',
        null=True,
        blank=True,
        help_text='Completed USDC withdrawal backing this review (XOR send_transaction)',
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    sent_usdc = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        validators=[MinValueValidator(Decimal('0.000001'))],
        help_text='USDC amount copied from the backing transaction',
    )
    received_usd = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Physical USD the reviewer received',
    )
    comment = models.TextField(blank=True, default='', validators=[MaxLengthValidator(280)])

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['financiera', '-created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(send_transaction__isnull=False, usdc_withdrawal__isnull=True)
                    | models.Q(send_transaction__isnull=True, usdc_withdrawal__isnull=False)
                ),
                name='review_backed_by_exactly_one_transaction',
            ),
            models.UniqueConstraint(
                fields=['send_transaction'],
                condition=models.Q(send_transaction__isnull=False),
                name='unique_review_per_send_transaction',
            ),
            models.UniqueConstraint(
                fields=['usdc_withdrawal'],
                condition=models.Q(usdc_withdrawal__isnull=False),
                name='unique_review_per_usdc_withdrawal',
            ),
        ]

    def __str__(self):
        return f'{self.rating}★ {self.sent_usdc} USDC → ${self.received_usd} ({self.financiera_id})'


class FinancieraReport(SoftDeleteModel):
    """User report against a listing, feeding the moderation queue."""

    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('reviewed', 'Revisado'),
        ('dismissed', 'Descartado'),
        ('action_taken', 'Acción tomada'),
    ]

    financiera = models.ForeignKey(
        Financiera, on_delete=models.CASCADE, related_name='reports'
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='financiera_reports',
    )
    reason = models.TextField(blank=True, default='', validators=[MaxLengthValidator(500)])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Report on {self.financiera_id} ({self.status})'
