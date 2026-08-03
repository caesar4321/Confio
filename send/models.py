from django.db import models
from django.conf import settings
from users.models import SoftDeleteModel
import uuid

# Create your models here.

def generate_send_transaction_id():
    """Generate a unique send transaction ID (32-char hex UUID)"""
    return uuid.uuid4().hex

class SendTransaction(SoftDeleteModel):
    """Model for storing send transaction data (direct user-to-user transfers)"""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
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
        # BSC dollar rails (Phase 2, 2026-07-30): cUSD+ vault shares and raw
        # USDT moved via sponsored EIP-7702 batches (send/bsc_flow.py).
        ('CUSD_PLUS', 'Confío Dollar Plus'),
        ('USDT', 'Tether USD'),
    ]

    # Unique identifier for the send transaction (internal)
    internal_id = models.CharField(
        max_length=32,
        unique=True,
        default=generate_send_transaction_id,
        editable=False
    )

    # User references (from our database) - LEGACY
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_transactions',
        null=True,
        blank=True,
        help_text='User who sent the transaction (null for external deposits)'
    )
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='received_transactions'
    )

    # NEW: Direct User/Business relationship fields
    sender_business = models.ForeignKey(
        'users.Business',
        on_delete=models.CASCADE,
        related_name='sent_transactions',
        null=True,
        blank=True,
        help_text='Business that sent the transaction (if sent by business)'
    )
    recipient_business = models.ForeignKey(
        'users.Business', 
        on_delete=models.CASCADE,
        related_name='received_transactions',
        null=True,
        blank=True,
        help_text='Business that received the transaction (if received by business)'
    )

    # Computed fields for GraphQL
    ACCOUNT_TYPE_CHOICES = [
        ('user', 'Personal'),
        ('business', 'Business'),
        ('external', 'External'),
    ]
    
    sender_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='user',
        help_text='Type of sender (user or business)'
    )
    recipient_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='user',
        help_text='Type of recipient (user or business)'
    )
    sender_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the sender'
    )
    recipient_display_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Display name for the recipient'
    )
    
    # Phone numbers at transaction time
    sender_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Sender phone number at transaction time'
    )
    recipient_phone = models.CharField(
        max_length=30,
        blank=True,
        help_text='Recipient phone number at transaction time'
    )

    # Blockchain addresses
    sender_address = models.CharField(max_length=66)  # Algorand addresses are 58 chars; 66 kept for legacy rows
    recipient_address = models.CharField(max_length=66)  # Algorand addresses are 58 chars; 66 kept for legacy rows

    # Transaction details
    amount = models.DecimalField(max_digits=19, decimal_places=6)  # Support up to 9,999,999,999,999.999999
    token_type = models.CharField(max_length=10, choices=TOKEN_TYPES)
    memo = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    transaction_hash = models.CharField(
        max_length=66, 
        blank=True,
        null=True,
        unique=True,
        help_text="Algorand transaction ID (52 chars; field kept at 66 for legacy rows)"
    )  # Algorand transaction id
    error_message = models.TextField(blank=True)
    
    # Idempotency key for preventing duplicate transactions
    idempotency_key = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text='Optional key to prevent duplicate transactions'
    )

    # BSC sends only: the EXACT sponsored call batch built at prepare time,
    # revalidated byte-for-byte at submit (presale/bsc_flow.py pattern —
    # the client can only ever sign what the server stored).
    bsc_calls_json = models.TextField(
        blank=True,
        default='',
        help_text='Sponsored 7702 call batch for BSC sends (server-built at prepare)'
    )
    
    # Invitation tracking
    is_invitation = models.BooleanField(
        default=False,
        help_text='True if this transaction includes an invitation to join Confío'
    )
    invitation_claimed = models.BooleanField(
        default=False,
        help_text='True if the invitation was claimed by the recipient'
    )
    invitation_reverted = models.BooleanField(
        default=False,
        help_text='True if the invitation expired and funds were returned to sender'
    )
    invitation_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the invitation expires (7 days after creation)'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['sender_user', 'status']),
            models.Index(fields=['recipient_user', 'status']),
            models.Index(fields=['sender_business', 'status']),
            models.Index(fields=['recipient_business', 'status']),
            models.Index(fields=['sender_address']),
            models.Index(fields=['recipient_address']),
            models.Index(fields=['created_at']),
            models.Index(fields=['idempotency_key']),
        ]
        constraints = [
            # Prevent duplicate transactions with same idempotency key from same user
            # Externally-originated inbounds (the cUSD+ scanner) have NO
            # sender_user, and Postgres treats NULLs as distinct — so the
            # constraint below does NOT dedupe them. Rescans would then create
            # a second row for the same log. This replaces the uniqueness the
            # old CusdPlusMovement.reference used to provide.
            models.UniqueConstraint(
                fields=['idempotency_key'],
                condition=models.Q(
                    sender_user__isnull=True,
                    idempotency_key__isnull=False,
                    deleted_at__isnull=True,
                ),
                name='unique_external_inbound_idempotency',
            ),
            models.UniqueConstraint(
                fields=['sender_user', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False, deleted_at__isnull=True),
                name='unique_send_idempotency'
            ),
        ]

    def __str__(self):
        return f"SEND-{self.transaction_hash or 'pending'}: {self.token_type} {self.amount} from {self.sender_user} to {self.recipient_user or self.recipient_address}"


# Update unified user activity on new send transactions
from django.db.models.signals import post_save
from django.dispatch import receiver
from users.utils import touch_user_activity


@receiver(post_save, sender=SendTransaction)
def send_txn_activity(sender, instance: SendTransaction, created, **kwargs):
    if created:
        try:
            if instance.sender_user_id:
                touch_user_activity(instance.sender_user_id)
            if instance.recipient_user_id:
                touch_user_activity(instance.recipient_user_id)
        except Exception:
            pass


@receiver(post_save, sender=SendTransaction)
def handle_first_cusd_on_send_receive(sender, instance: SendTransaction, **kwargs):
    """Trigger ICP/Rating modal arming when a user receives their first cUSD via P2P send.

    Fires on any save where the row is now CONFIRMED + cUSD + has a recipient_user.
    Idempotent: mark_first_cusd_acquired_if_null is a no-op if already set.
    No confirmed_at column on SendTransaction, so use updated_at as the proxy
    for confirmation time — when status transitions to CONFIRMED, updated_at
    is set to that moment by auto_now=True.
    """
    try:
        if instance.is_deleted:
            return
        if instance.status != 'CONFIRMED' or instance.token_type != 'CUSD':
            return
        if instance.recipient_user_id is None:
            return
        from users.helpers import mark_first_cusd_acquired_if_null, arm_rating_prompt_if_eligible
        recipient = instance.recipient_user
        mark_first_cusd_acquired_if_null(recipient, instance.updated_at)
        recipient.refresh_from_db(
            fields=['confio_icp_captured_at', 'rating_prompt_due_at', 'confio_rating_prompted_at']
        )
        arm_rating_prompt_if_eligible(recipient)
    except Exception:
        # Swallow — never block the send-transaction write path on modal-arming.
        pass


class PhoneInvite(SoftDeleteModel):
    """Track phone-based invites for non-Confío friends (off-chain index)."""
    # One escrow slot, one row. Every transition out of an in-flight state is
    # a compare-and-set, and every in-flight state is resolved by a receipt,
    # never by "we broadcast it, so it happened" (Codex audit 2026-08-02).
    #
    # 'pending' used to mean BOTH "prepared, nothing on chain" and "escrow
    # funded, awaiting claim". That conflation is what let a second submit
    # broadcast over the first, and let the auto-claim try to release a slot
    # that no transaction had funded yet. They are separate states now.
    STATUS_CHOICES = [
        ('draft', 'Prepared, nothing broadcast'),
        ('creating', 'Create batch in flight'),
        ('pending', 'Escrowed, awaiting claim'),
        ('claiming', 'Claim in flight'),
        ('claimed', 'Claimed'),
        # In-flight reclaim (audit 2026-07-31 P3): the reclaim batch is
        # broadcast but not yet final. The row is NOT 'reclaimed' until the
        # confirm task sees the batch mine — a reverted reclaim (e.g. the
        # invitee claimed first) must not leave the DB claiming otherwise.
        ('reclaiming', 'Reclaim in flight'),
        ('reclaimed', 'Reclaimed'),
        ('failed', 'Create never landed'),
    ]

    # Which chain actually holds the money. Two invite rails share this table
    # (Algorand box storage and the BSC ConfioInviteEscrow), and each used to
    # infer ownership differently — BSC from a non-empty inviter_address,
    # Algorand from nothing at all, which let it pick up a BSC row and hand a
    # 64-hex escrow id to the box API as a key (Codex audit 2026-08-02).
    #
    # Stated, never inferred. token_type cannot do this job: CONFIO exists on
    # both rails.
    RAIL_CHOICES = [('algorand', 'Algorand'), ('bsc', 'BNB Smart Chain')]
    rail = models.CharField(max_length=8, choices=RAIL_CHOICES,
                            default='algorand', db_index=True)

    # Deterministic invitation id used on-chain (derived from phone_key)
    invitation_id = models.CharField(max_length=64, unique=True)

    # Canonical phone key and raw inputs for audit
    phone_key = models.CharField(max_length=32, db_index=True)
    phone_country = models.CharField(max_length=2, blank=True)
    phone_number = models.CharField(max_length=20)

    inviter_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='phone_invites_sent'
    )

    # The BSC address the escrow holds the funds under. Recorded rather than
    # re-derived: the escrow keys by (inviter, inviteId), and a user's invite
    # may come from a personal OR a business account, so guessing at claim time
    # can look up a slot that was never funded.
    inviter_address = models.CharField(max_length=42, blank=True, default='')

    # Optional reference to the persisted send transaction row
    send_transaction = models.ForeignKey(
        'send.SendTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='phone_invite'
    )

    amount = models.DecimalField(max_digits=19, decimal_places=6)
    token_type = models.CharField(max_length=10, choices=SendTransaction.TOKEN_TYPES)
    message = models.CharField(max_length=256, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='phone_invites_claimed'
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_txid = models.CharField(max_length=66, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['phone_key', 'status']),
            models.Index(fields=['invitation_id']),
        ]
        ordering = ['-created_at']
        verbose_name = 'Phone invite'
        verbose_name_plural = 'Phone invites'

    def __str__(self):
        return f"Invite {self.invitation_id} to {self.phone_key} {self.amount} {self.token_type} ({self.status})"
