"""
cUSD+ conversion tracking — the server-side OBSERVER of the client-driven
saga (contracts/cusd_plus/ORCHESTRATION.md).

The server never moves user funds: the client signs every leg. These rows
power resume-on-foreground, the Movimientos history, bridge polling, gas
dusting, reconciliation and support. Mirrors conversion.models.Conversion
conventions (actor pattern, soft delete, uuid internal id).
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class BnbAutoConvert(models.Model):
    """Ledger of relay-observed BNB→USDT auto-convert swaps.

    Mis-deposited BNB at a user's BSC address is swapped to USDT via
    PancakeSwap (client-signed, mirrors the mainnet ALGO→USDC auto-convert).
    Every row is written by the relay at submission time, so this table is
    the authoritative allowlist for outbound native BNB: an outbound BNB
    transfer NOT in this table is dust extraction (farming) and disqualifies
    the address's owner from further gas/MBR subsidies. The swap's USDT
    output lands at the user's own address, where monitor_bridge_arrivals
    picks it up like any external deposit.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='bnb_auto_converts',
    )
    # Wei doesn't fit typical decimal columns; store as digits string.
    value_wei = models.CharField(max_length=32)
    tx_hash = models.CharField(max_length=66, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_bnb_auto_converts'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='cpbac_user_created_idx'),
            models.Index(fields=['tx_hash'], name='cpbac_tx_hash_idx'),
        ]

    def __str__(self):
        return f'BNB autoconvert {self.value_wei} wei [{self.tx_hash or "pending"}]'


class SponsoredBatch(models.Model):
    """Audit ledger of EIP-7702 sponsored batch executions (sponsor_7702).

    One row per type-4 transaction the sponsor broadcast on a user's
    behalf: the exact validated call batch, the gas ceiling the sponsor
    committed to, and the receipt outcome. `noop_failed` flags the 7702
    silent-failure mode — the tx mined "successfully" but emitted no logs,
    meaning the delegation never applied (authorization nonce raced) and
    nothing executed; the client retries with a fresh authorization.
    """
    STATUS_CHOICES = [
        # 'signed' is the DURABLE pre-broadcast state (audit 2026-07-31
        # P1-2): the row + deterministic tx_hash are written BEFORE
        # eth_sendRawTransaction, so a crash mid-broadcast leaves a
        # reconcilable record instead of a lost chain tx.
        ('signed', 'Signed, broadcast unconfirmed'),
        ('sent', 'Broadcast, receipt pending'),
        ('confirmed', 'Mined, executed and final'),
        ('reverted', 'Mined but reverted'),
        ('noop_failed', 'Mined, but delegation did not apply (no-op)'),
        ('reorged', 'Was mined then orphaned by a reorg'),
        # A 'signed' row whose deterministic hash no node knows after the
        # grace window: the broadcast never landed and the KMS-signed raw is
        # not reproducible. Terminal-fail so the domain flow fails and the
        # user can retry (the delegate's monotonic nonce makes a retry safe).
        ('dropped', 'Signed but never reached the chain'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='sponsored_batches',
    )
    user_bsc_address = models.CharField(max_length=42)
    # 'subscribe' | 'redeem' | 'presale_buy' | Phase-2 kinds:
    # send_cusd_plus | send_redeem | send_usdt | pay_cusd_plus | pay_usdt |
    # payroll_fund | payroll_payout | invite_create | invite_reclaim | ...
    kind = models.CharField(max_length=32)
    # The domain row this batch settles (SendTransaction / PaymentTransaction
    # / PayrollItem / …) — confirm tasks verify (kind, source_id, tx_hash)
    # against the row before settling, so one batch can only settle its own
    # source (audit P2 batch isolation).
    source_id = models.BigIntegerField(null=True, blank=True)
    num_calls = models.PositiveSmallIntegerField()
    calls_json = models.TextField()
    tx_hash = models.CharField(max_length=66, blank=True)
    # Delegate nonce (7702) or 0 for plain KMS txs — matched against the
    # BatchExecuted(nonce,...) log to prove the batch actually executed.
    delegate_nonce = models.BigIntegerField(null=True, blank=True)
    # Finality: the block the receipt landed in; re-checked canonical before
    # settling and after, so a reorg flips the row to 'reorged'.
    block_number = models.BigIntegerField(null=True, blank=True)
    block_hash = models.CharField(max_length=66, blank=True)
    gas_limit = models.PositiveIntegerField()
    # Wei doesn't fit typical decimal columns; store as digits string.
    max_fee_wei = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='sent')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'cusd_plus_sponsored_batches'
        indexes = [
            models.Index(fields=['user', 'created_at'], name='cpsb_user_created_idx'),
            models.Index(fields=['tx_hash'], name='cpsb_tx_hash_idx'),
            models.Index(fields=['status'], name='cpsb_status_idx'),
            models.Index(fields=['kind', 'source_id'], name='cpsb_kind_source_idx'),
        ]
        constraints = [
            # One batch per tx hash — blocks the same broadcast being
            # recorded twice (audit P2 batch isolation). Partial so legacy
            # blank-hash rows don't collide.
            models.UniqueConstraint(
                fields=['tx_hash'],
                condition=models.Q(tx_hash__gt=''),
                name='cpsb_unique_tx_hash',
            ),
        ]

    def __str__(self):
        return f'7702 {self.kind} x{self.num_calls} [{self.status}] {self.tx_hash or "pending"}'


