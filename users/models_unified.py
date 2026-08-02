# Django models for unified transaction tables
import logging

from django.db import models
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# The app's account screens query these EXACT strings — savings asks for
# ['CUSD_PLUS','USDT'], cUSD for ['CUSD','USDC','ALGO'], CONFIO for
# ['CONFIO'] (AccountDetailScreen accountTokenTypes). A row tagged with
# anything else belongs to no screen: it is money the user can never see.
# That has already happened twice in production — 67 conversion rows written
# as lowercase 'cUSD', and the presale card the BSC rail filed under 'CUSD'.
CANONICAL_TOKEN_TYPES = frozenset({'CUSD', 'CONFIO', 'USDC', 'ALGO', 'CUSD_PLUS', 'USDT'})

# Every non-canonical spelling any writer in this repo can produce. The ramp
# rail is the main source: Koywe reports a product name, not a ledger token
# (ramps/koywe_sync.py sets final_currency to 'CUSD+', 'USDT BSC', or
# KOYWE_CRYPTO_SYMBOL), and ramps/signals.py passes it straight through.
TOKEN_TYPE_ALIASES = {
    'CUSD+': 'CUSD_PLUS',
    'CUSDPLUS': 'CUSD_PLUS',
    'CUSD PLUS': 'CUSD_PLUS',
    'USDT BSC': 'USDT',
    'USDT-BSC': 'USDT',
    'USDTBSC': 'USDT',
    'USDC ALGORAND': 'USDC',
    'USDC POLYGON': 'USDC',
    'USDC-POLYGON': 'USDC',
}


def canonical_token_type(value):
    """Fold a writer's spelling into the token the app actually queries."""
    raw = (value or '').strip().upper()
    return TOKEN_TYPE_ALIASES.get(raw, raw)


class UnifiedTransactionTable(models.Model):
    """
    Actual table for unified transactions across all transaction types.
    Maintains foreign keys to source tables for data integrity.
    """
    TRANSACTION_TYPES = [
        ('send', 'Send/Receive'),
        ('payment', 'Payment'),
        ('payroll', 'Payroll'),
        ('conversion', 'Conversion'),
        ('exchange', 'P2P Exchange'),
        ('reward', 'Reward'),
        ('presale', 'Presale Purchase'),
        ('ramp', 'Ramp'),
        ('humanitarian', 'Humanitarian Aid'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PENDING_SIG', 'Pending Signature'),
        ('PENDING_BLOCKCHAIN', 'Pending Blockchain'),
        ('SPONSORING', 'Sponsoring'),
        ('SIGNED', 'Signed'),
        ('SUBMITTED', 'Submitted'),
        ('CONFIRMED', 'Confirmed'),
        ('FAILED', 'Failed'),
        ('AML_REVIEW', 'Under AML Review')
    ]

    TOKEN_TYPES = [
        ('CUSD', 'Confío Dollar'),
        ('CONFIO', 'Confío Token'),
        ('USDC', 'USD Coin'),
        ('ALGO', 'ALGO'),
        # BSC dollar rails (Phase 2, 2026-07-30). The resolver upper-cases
        # token_type on filter, so these are safe additive choices.
        ('CUSD_PLUS', 'Confío Dollar Plus'),
        ('USDT', 'Tether USD'),
    ]

    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
        ('external', 'External'),
    ]

    # Primary key
    id = models.BigAutoField(primary_key=True)
    
    # Transaction type
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, db_index=True)
    
    # Foreign keys to source tables (only one will be set)
    send_transaction = models.OneToOneField(
        'send.SendTransaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    payment_transaction = models.OneToOneField(
        'payments.PaymentTransaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    conversion = models.OneToOneField(
        'conversion.Conversion',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    p2p_trade = models.OneToOneField(
        'p2p_exchange.P2PTrade',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    payroll_item = models.OneToOneField(
        'payroll.PayrollItem',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    referral_reward_event = models.OneToOneField(
        'achievements.ReferralRewardEvent',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )

    presale_purchase = models.OneToOneField(
        'presale.PresalePurchase',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction'
    )
    ramp_transaction = models.OneToOneField(
        'ramps.RampTransaction',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction',
    )
    humanitarian_donation = models.OneToOneField(
        'humanitarian.HumanitarianDonation',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction',
    )
    humanitarian_release = models.OneToOneField(
        'humanitarian.HumanitarianRelease',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='unified_transaction',
    )
    
    # Denormalized fields for quick access/filtering
    amount = models.CharField(max_length=32)
    # What `amount` actually counts. cUSD+ and USDY ACCRUE, so a share count
    # and a dollar value are different numbers that drift further apart every
    # day — and the ledger stored both under the same column with nothing
    # saying which. A card reading "10.00 cUSD+" may correspond to 9.52
    # shares at $1.05/share, and no receipt could be checked against the
    # ERC-20 transfer. Recording the unit does not change any number a user
    # sees; it makes the number auditable.
    AMOUNT_DENOMINATIONS = [
        ('TOKEN_UNITS', 'Token units (non-accruing: 1 unit = 1 token)'),
        ('USD_VALUE', 'Dollar value at the time of the transaction'),
        ('SHARES', 'Accruing-vault share count'),
    ]
    amount_denomination = models.CharField(
        max_length=16, choices=AMOUNT_DENOMINATIONS, default='TOKEN_UNITS',
        help_text='Unit of `amount`. Every current cUSD+ writer stores a '
                  'dollar value, not shares — see save().',
    )
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    transaction_hash = models.CharField(max_length=66, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    
    # Sender info
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='unified_table_sent_transactions',
        null=True,
        blank=True
    )
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='unified_table_sent_transactions',
        null=True,
        blank=True
    )
    sender_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    sender_display_name = models.CharField(max_length=255, blank=True)
    sender_phone = models.CharField(max_length=30, blank=True)
    sender_address = models.CharField(max_length=66, blank=True, default='')
    
    # Counterparty info (recipient for sends, merchant for payments)
    counterparty_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='unified_table_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='unified_table_counterparty_transactions',
        null=True,
        blank=True
    )
    counterparty_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    counterparty_display_name = models.CharField(max_length=255, blank=True)
    counterparty_phone = models.CharField(max_length=30, blank=True, null=True)
    counterparty_address = models.CharField(max_length=66, blank=True, default='')
    
    # Additional fields
    description = models.TextField(blank=True)
    invoice_id = models.CharField(max_length=32, blank=True, null=True)
    payment_reference_id = models.CharField(max_length=32, blank=True, null=True)
    
    # Address fields for easy filtering
    from_address = models.CharField(max_length=66, blank=True, default='')
    to_address = models.CharField(max_length=66, blank=True, default='')
    
    # Invitation tracking fields
    is_invitation = models.BooleanField(default=False)
    invitation_claimed = models.BooleanField(default=False)
    invitation_reverted = models.BooleanField(default=False)
    invitation_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)  # When record is created in unified table
    transaction_date = models.DateTimeField()  # Original transaction date from source
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'unified_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
            models.Index(fields=['sender_user', '-created_at']),
            models.Index(fields=['sender_business', '-created_at']),
            models.Index(fields=['counterparty_user', '-created_at']),
            models.Index(fields=['counterparty_business', '-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['token_type', '-created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(token_type__in=sorted(CANONICAL_TOKEN_TYPES)),
                name='unified_token_type_canonical',
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalise here rather than in each writer. There are a dozen of
        # them across send, payments, payroll, conversion, ramps, presale,
        # humanitarian and referrals, and the ledger is only correct if every
        # one independently spells the token the way the app queries it —
        # which is precisely the agreement that has failed twice. The
        # CheckConstraint above is the backstop for paths that bypass save()
        # (bulk .update()), and a loud write failure is the right outcome for
        # a money ledger: an unqueryable row is money the user never sees.
        canonical = canonical_token_type(self.token_type)
        if canonical != (self.token_type or ''):
            logger.info('unified: token_type %r normalised to %r (%s)',
                        self.token_type, canonical, self.transaction_type)
        if canonical not in CANONICAL_TOKEN_TYPES:
            logger.error(
                'unified: %s writer produced non-canonical token_type %r — this row '
                'would belong to no account screen; add an alias to '
                'TOKEN_TYPE_ALIASES', self.transaction_type, self.token_type,
            )
        self.token_type = canonical

        # Every writer that produces a CUSD_PLUS row today stores a DOLLAR
        # VALUE, not a share count: the savings conversion writes the USD
        # quote, the scanner converts shares through price-per-share before
        # recording, and send/payroll store the requested dollars while the
        # chain moves shares. Stamp that convention rather than trust each
        # writer to remember it. A writer that genuinely records shares must
        # set amount_denomination='SHARES' explicitly.
        if canonical == 'CUSD_PLUS' and self.amount_denomination == 'TOKEN_UNITS':
            self.amount_denomination = 'USD_VALUE'
        super().save(*args, **kwargs)

    def get_direction_for_address(self, address):
        """
        Determine if this transaction is incoming or outgoing for a given address.

        Case-INSENSITIVE on purpose. An EVM address is the same address in any
        case — the mixed case is only an EIP-55 checksum — and the two sides
        genuinely disagree here: accounts store the checksummed form while the
        send flow lower-cases what it writes. An exact == made every BSC row
        resolve to 'unknown', which renders as an "Unknown" counterparty and an
        unsigned amount. Algorand's base32 is upper-case by convention, so
        folding is harmless there.
        """
        if not address:
            return 'unknown'
        target = str(address).strip().lower()
        if not target:
            return 'unknown'
        if self.from_address and str(self.from_address).strip().lower() == target:
            return 'sent'
        if self.to_address and str(self.to_address).strip().lower() == target:
            return 'received'
        return 'unknown'
            
    def get_display_info_for_address(self, address):
        """
        Get display information based on the perspective of the given address
        """
        direction = self.get_direction_for_address(address)
        
        if direction == 'sent':
            return {
                'direction': 'sent',
                'counterparty_name': self.counterparty_display_name,
                'counterparty_type': self.counterparty_type,
                'amount': f'-{self.amount}',
                'description': self.description or 'Enviado'
            }
        elif direction == 'received':
            return {
                'direction': 'received',
                'counterparty_name': self.sender_display_name,
                'counterparty_type': self.sender_type,
                'amount': f'+{self.amount}',
                'description': self.description or 'Recibido'
            }
        else:
            return {
                'direction': 'unknown',
                'counterparty_name': 'Unknown',
                'counterparty_type': 'unknown',
                'amount': self.amount,
                'description': self.description or 'Unknown transaction'
            }

    # One conversion FK now covers both rails, so these read the row
    # directly. They used to fall back to parsing the Spanish description
    # ("Conversión: 2.99 USDC → 2.99 cUSD") with a regex that knew only the
    # Algorand pair — which is how savings rows ended up untyped, with no
    # tokens and no title.
    def get_conversion_type(self):
        if self.transaction_type == 'conversion' and self.conversion_id:
            return self.conversion.conversion_type
        return None

    def get_from_amount(self):
        if self.transaction_type == 'conversion' and self.conversion_id:
            return self.conversion.from_amount
        return None

    def get_to_amount(self):
        if self.transaction_type == 'conversion' and self.conversion_id:
            return self.conversion.to_amount
        return None

    def get_from_token(self):
        if self.transaction_type == 'conversion' and self.conversion_id:
            return self.conversion.from_token
        return None

    def get_to_token(self):
        if self.transaction_type == 'conversion' and self.conversion_id:
            return self.conversion.to_token
        return None

    @property
    def internal_id(self):
        """Return standardized internal_id from linked source models"""
        if self.transaction_type == 'exchange' and self.p2p_trade:
            return self.p2p_trade.internal_id
        if self.transaction_type == 'payroll' and self.payroll_item:
            return self.payroll_item.internal_id
        if self.transaction_type == 'payment' and self.payment_transaction:
            return self.payment_transaction.internal_id
        if self.transaction_type == 'send' and self.send_transaction:
            return self.send_transaction.internal_id
        if self.transaction_type == 'conversion' and self.conversion:
            return self.conversion.internal_id
        if self.transaction_type == 'reward' and self.referral_reward_event:
            return self.referral_reward_event.internal_id
        if self.transaction_type == 'presale' and self.presale_purchase:
            return self.presale_purchase.internal_id
        if self.transaction_type == 'ramp' and self.ramp_transaction:
            return self.ramp_transaction.internal_id
        if self.transaction_type == 'humanitarian' and self.humanitarian_donation:
            return self.humanitarian_donation.public_id
        if self.transaction_type == 'humanitarian' and self.humanitarian_release:
            return self.humanitarian_release.public_id
        return None

    @property
    def p2p_trade_id(self):
        """Return P2P trade ID if this is an exchange transaction"""
        if self.transaction_type == 'exchange' and self.p2p_trade:
            # Return internal_id as the public ID
            return self.p2p_trade.internal_id
        return None

    def __str__(self):
        return f"{self.transaction_type.upper()}-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount}"
