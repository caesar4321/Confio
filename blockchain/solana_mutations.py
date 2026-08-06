"""Generic GraphQL entry points for Solana fee sponsorship."""

from __future__ import annotations

import logging
import hashlib

import graphene
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from blockchain.solana_sponsor_service import (
    SolanaSponsorPolicyError,
    SolanaSponsorService,
)
from users.models import Account
from blockchain.models import (
    SolanaSponsorDailySpend,
    SolanaSponsorBalanceState,
    SolanaSponsorGlobalDailySpend,
    SolanaSponsoredTransaction,
)

logger = logging.getLogger(__name__)
LIABILITY_STATUSES = (
    "reserved",
    "signed",
    "sent",
    "unknown",
    "confirmed_pending",
)


def _shared_cache_available() -> bool:
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    return any(
        atomic_backend in backend
        for atomic_backend in ("RedisCache", "PyMemcacheCache", "PyLibMCCache")
    )


def _reserve_sponsorship_budget(
    *,
    account,
    user,
    fee_lamports,
    observed_balance_lamports,
    observed_balance_slot,
    validated,
):
    """Atomically reserve per-account and relay-wide UTC daily fee budgets."""
    day = timezone.now().date()
    message_hash = hashlib.sha256(validated.message_bytes).hexdigest()
    account_limit = int(settings.SOLANA_SPONSOR_ACCOUNT_DAILY_BUDGET_LAMPORTS)
    global_limit = int(settings.SOLANA_SPONSOR_GLOBAL_DAILY_BUDGET_LAMPORTS)

    with transaction.atomic():
        SolanaSponsorGlobalDailySpend.objects.get_or_create(day=day)
        global_spend = SolanaSponsorGlobalDailySpend.objects.select_for_update().get(
            day=day
        )
        SolanaSponsorBalanceState.objects.get_or_create(singleton=1)
        balance_state = SolanaSponsorBalanceState.objects.select_for_update().get(
            singleton=1
        )
        balance_state.observed_balance_lamports = observed_balance_lamports
        SolanaSponsoredTransaction.objects.filter(
            status="confirmed_pending",
            confirmation_slot__lte=observed_balance_slot,
        ).update(status="confirmed", updated_at=timezone.now())

        existing = SolanaSponsoredTransaction.objects.select_for_update().filter(
            message_hash=message_hash
        ).first()
        if existing:
            if existing.account_id != account.id or existing.fee_lamports != fee_lamports:
                raise SolanaSponsorPolicyError("sponsorship_replay_conflict")
            if existing.status in ("failed", "expired"):
                unresolved_lamports = int(
                    SolanaSponsoredTransaction.objects.filter(
                        status__in=LIABILITY_STATUSES
                    ).aggregate(total=Sum("fee_lamports"))["total"]
                    or 0
                )
                if observed_balance_lamports - unresolved_lamports - fee_lamports < int(
                    settings.SOLANA_SPONSOR_MIN_BALANCE_LAMPORTS
                ):
                    raise SolanaSponsorPolicyError("sponsor_balance_low")
                existing.status = "reserved"
                existing.save(update_fields=["status", "updated_at"])
                balance_state.save(
                    update_fields=["observed_balance_lamports", "updated_at"]
                )
            return existing

        SolanaSponsorDailySpend.objects.get_or_create(account=account, day=day)
        account_spend = SolanaSponsorDailySpend.objects.select_for_update().get(
            account=account, day=day
        )
        if account_spend.spent_lamports + fee_lamports > account_limit:
            raise SolanaSponsorPolicyError("account_daily_budget_exceeded")
        if global_spend.spent_lamports + fee_lamports > global_limit:
            raise SolanaSponsorPolicyError("global_daily_budget_exceeded")
        unresolved_lamports = int(
            SolanaSponsoredTransaction.objects.filter(
                status__in=LIABILITY_STATUSES
            ).aggregate(total=Sum("fee_lamports"))["total"]
            or 0
        )
        if observed_balance_lamports - unresolved_lamports - fee_lamports < int(
            settings.SOLANA_SPONSOR_MIN_BALANCE_LAMPORTS
        ):
            balance_state.save(
                update_fields=[
                    "observed_balance_lamports",
                    "updated_at",
                ]
            )
            raise SolanaSponsorPolicyError("sponsor_balance_low")

        account_spend.spent_lamports += fee_lamports
        account_spend.transaction_count += 1
        account_spend.save(
            update_fields=["spent_lamports", "transaction_count", "updated_at"]
        )
        global_spend.spent_lamports += fee_lamports
        global_spend.transaction_count += 1
        global_spend.save(
            update_fields=["spent_lamports", "transaction_count", "updated_at"]
        )
        balance_state.save(
            update_fields=[
                "observed_balance_lamports",
                "updated_at",
            ]
        )
        return SolanaSponsoredTransaction.objects.create(
            user=user,
            account=account,
            message_hash=message_hash,
            recent_blockhash=str(validated.transaction.message.recent_blockhash),
            fee_lamports=fee_lamports,
        )


def _reconcile_outstanding_sponsorships(service):
    """Release cross-day balance liabilities only with confirmed RPC proof."""
    validity_cache = {}

    def blockhash_is_valid(blockhash):
        if blockhash in validity_cache:
            return validity_cache[blockhash]
        if len(validity_cache) >= 3:
            return None
        result = service._rpc(
            "isBlockhashValid",
            [blockhash, {"commitment": "confirmed"}],
        )
        validity_cache[blockhash] = bool((result or {}).get("value"))
        return validity_cache[blockhash]

    unsigned_rows = list(
        SolanaSponsoredTransaction.objects.filter(status="reserved", signature="")
        .order_by("created_at")[:20]
    )
    for row in unsigned_rows:
        valid = blockhash_is_valid(row.recent_blockhash)
        if valid is False:
            SolanaSponsoredTransaction.objects.filter(
                pk=row.pk, status="reserved", signature=""
            ).update(status="expired", updated_at=timezone.now())

    rows = list(
        SolanaSponsoredTransaction.objects.filter(
            status__in=("signed", "sent", "unknown"),
        )
        .exclude(signature="")
        .order_by("created_at")[:20]
    )
    if not rows:
        return
    result = service._rpc(
        "getSignatureStatuses",
        [[row.signature for row in rows], {"searchTransactionHistory": True}],
    )
    statuses = (result or {}).get("value") or []
    for row, status in zip(rows, statuses):
        if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
            confirmation_slot = status.get("slot")
            if confirmation_slot is None:
                continue
            SolanaSponsoredTransaction.objects.filter(
                pk=row.pk, status__in=LIABILITY_STATUSES
            ).update(
                status="confirmed_pending",
                confirmation_slot=int(confirmation_slot),
                updated_at=timezone.now(),
            )
            continue
        if status is None:
            valid = blockhash_is_valid(row.recent_blockhash)
            if valid is False:
                SolanaSponsoredTransaction.objects.filter(
                    pk=row.pk, status__in=LIABILITY_STATUSES
                ).update(status="expired", updated_at=timezone.now())


def _rate_limited(user_id, kind: str, limit: int) -> bool:
    key = f"solana_sponsor:{kind}:{user_id}"
    try:
        if cache.add(key, 1, timeout=60):
            return False
        return cache.incr(key) > limit
    except (ValueError, NotImplementedError):
        count = int(cache.get(key, 0)) + 1
        cache.set(key, count, 60)
        return count > limit


def _active_solana_account(info, *, permission=None):
    user = getattr(info.context, "user", None)
    if not user or not user.is_authenticated:
        return None, "auth_required"
    from users.jwt_context import get_jwt_business_context_with_validation

    ctx = get_jwt_business_context_with_validation(
        info, required_permission=permission
    )
    if not ctx:
        return None, "invalid_account_context"
    if ctx.get("account_type") == "business" and ctx.get("business_id"):
        account = Account.objects.filter(
            business_id=ctx["business_id"],
            account_type="business",
            deleted_at__isnull=True,
        ).order_by("account_index").first()
    else:
        account = Account.objects.filter(
            user=user,
            account_type=ctx.get("account_type", "personal"),
            account_index=ctx.get("account_index", 0),
            deleted_at__isnull=True,
        ).first()
    if not account:
        return None, "account_not_found"
    if not account.solana_address:
        return None, "no_solana_address"
    return account, None


class PrepareSolanaSponsoredTransaction(graphene.Mutation):
    class Arguments:
        pass

    success = graphene.Boolean(required=True)
    sponsor_address = graphene.String()
    blockhash = graphene.String()
    last_valid_block_height = graphene.Int()
    max_fee_lamports = graphene.Int()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info):
        account, error = _active_solana_account(info)
        if error:
            return cls(success=False, error=error)
        if not getattr(settings, "SOLANA_SPONSOR_ENABLED", False):
            return cls(success=False, error="disabled")
        if getattr(settings, "SOLANA_SPONSOR_REQUIRE_SHARED_CACHE", True) and not _shared_cache_available():
            return cls(success=False, error="shared_cache_required")
        try:
            if _rate_limited(info.context.user.id, "prepare", 30):
                return cls(success=False, error="rate_limited")
            prepared = SolanaSponsorService().prepare()
            return cls(
                success=True,
                sponsor_address=prepared["sponsorAddress"],
                blockhash=prepared["blockhash"],
                last_valid_block_height=prepared["lastValidBlockHeight"],
                max_fee_lamports=prepared["maxFeeLamports"],
            )
        except SolanaSponsorPolicyError as exc:
            return cls(success=False, error=exc.code)
        except Exception:
            logger.exception("Solana sponsor prepare failed for account %s", account.id)
            return cls(success=False, error="sponsor_unavailable")


class SponsorSolanaTransaction(graphene.Mutation):
    """Sponsor any safe user-signed Solana transaction.

    Ordinary programs need no product registration because they cannot touch
    the sponsor unless account zero is passed to them. Sponsor-aware
    instructions are admitted only through the central exact policy registry.
    """

    class Arguments:
        transaction = graphene.String(
            required=True, description="Base64 partially signed Solana transaction"
        )

    success = graphene.Boolean(required=True)
    signature = graphene.String()
    fee_lamports = graphene.Int()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, transaction):
        account, error = _active_solana_account(info, permission="send_funds")
        if error:
            return cls(success=False, error=error)
        if not getattr(settings, "SOLANA_SPONSOR_ENABLED", False):
            return cls(success=False, error="disabled")
        if getattr(settings, "SOLANA_SPONSOR_REQUIRE_SHARED_CACHE", True) and not _shared_cache_available():
            return cls(success=False, error="shared_cache_required")
        user_id = info.context.user.id
        try:
            if _rate_limited(user_id, "submit", 10):
                return cls(success=False, error="rate_limited")
            cooldown_key = f"solana_sponsor:cooldown:{account.solana_address}"
            if not cache.add(cooldown_key, 1, timeout=5):
                return cls(success=False, error="rate_limited")
        except Exception:
            logger.exception("Solana sponsor throttle unavailable")
            return cls(success=False, error="sponsor_unavailable")

        reservation = None

        def lookup_transaction(validated):
            nonlocal reservation
            message_hash = hashlib.sha256(validated.message_bytes).hexdigest()
            existing = SolanaSponsoredTransaction.objects.filter(
                message_hash=message_hash
            ).first()
            if not existing:
                return None
            if existing.account_id != account.id:
                raise SolanaSponsorPolicyError("sponsorship_replay_conflict")
            if existing.status in ("sent", "confirmed") and not existing.signature:
                raise SolanaSponsorPolicyError("sponsorship_record_invalid")
            reservation = existing
            return {
                "status": existing.status,
                "signature": existing.signature,
                "fee_lamports": existing.fee_lamports,
            }

        def authorize_fee(
            fee_lamports, observed_balance_lamports, observed_balance_slot, validated
        ):
            nonlocal reservation
            reservation = _reserve_sponsorship_budget(
                account=account,
                user=info.context.user,
                fee_lamports=fee_lamports,
                observed_balance_lamports=observed_balance_lamports,
                observed_balance_slot=observed_balance_slot,
                validated=validated,
            )

        def record_signature(signature, validated):
            if reservation:
                SolanaSponsoredTransaction.objects.filter(
                    pk=reservation.pk,
                    status__in=("reserved", "unknown"),
                ).update(signature=signature, status="signed", updated_at=timezone.now())
                reservation.signature = signature
                reservation.status = "signed"

        try:
            service = SolanaSponsorService()
            _reconcile_outstanding_sponsorships(service)
            try:
                result = service.sponsor_and_send(
                    transaction,
                    expected_user_signer=account.solana_address,
                    fee_authorizer=authorize_fee,
                    transaction_lookup=lookup_transaction,
                    signature_recorder=record_signature,
                )
            except SolanaSponsorPolicyError as exc:
                if exc.code != "sponsor_account_referenced":
                    raise
                from blockchain.solana_policies import sponsor_reference_policy

                result = service.sponsor_and_send(
                    transaction,
                    expected_user_signer=account.solana_address,
                    policy_hook=sponsor_reference_policy(),
                    allow_sponsor_account_reference=True,
                    fee_authorizer=authorize_fee,
                    transaction_lookup=lookup_transaction,
                    signature_recorder=record_signature,
                )
            if reservation:
                SolanaSponsoredTransaction.objects.filter(
                    pk=reservation.pk,
                    status__in=("reserved", "signed", "sent", "unknown"),
                ).update(
                    signature=result["signature"], status="sent", updated_at=timezone.now()
                )
            return cls(
                success=True,
                signature=result["signature"],
                fee_lamports=result["feeLamports"],
            )
        except SolanaSponsorPolicyError as exc:
            if reservation:
                if reservation.signature:
                    SolanaSponsoredTransaction.objects.filter(
                        pk=reservation.pk, status__in=("reserved", "signed")
                    ).update(status="unknown", updated_at=timezone.now())
                else:
                    SolanaSponsoredTransaction.objects.filter(
                        pk=reservation.pk, status="reserved"
                    ).update(status="failed", updated_at=timezone.now())
            return cls(success=False, error=exc.code)
        except Exception:
            if reservation:
                if reservation.signature:
                    SolanaSponsoredTransaction.objects.filter(
                        pk=reservation.pk, status__in=("reserved", "signed")
                    ).update(status="unknown", updated_at=timezone.now())
                else:
                    SolanaSponsoredTransaction.objects.filter(
                        pk=reservation.pk, status="reserved"
                    ).update(status="failed", updated_at=timezone.now())
            logger.exception("Solana sponsorship failed for account %s", account.id)
            return cls(success=False, error="sponsor_unavailable")
