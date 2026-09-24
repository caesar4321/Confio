"""On-chain proof for direct USDC transfers (Algorand era, Sept 2025 onward).

USDCDeposit / USDCWithdrawal carry no transaction hash, and a COMPLETED row
is not evidence: the legacy CreateUSDCDeposit / CreateUSDCWithdrawal
mutations mark client-supplied amounts completed on the spot. Before a
direct transfer may count in the public "Movido" metric, this module finds
the matching asset transfer on the Algorand indexer and records it as a
DirectTransferProof.

A proof is recorded only when ALL of these hold:
- same wallet, same counterparty, same USDC amount (base units, exact),
  confirmed within PROOF_WINDOW of the row's creation;
- the counterparty is outside Confío: not any Account address (deleted
  accounts included), not a retired Algorand address (wallet migration to
  BSC clears Account.algorand_address and keeps the old one only in
  RetiredWalletAddress), not the sponsor — transfers between Confío wallets
  are not money moving in/out;
- the transfer is not a Dollar+ -> dollar bridge arrival (its hash is on a
  from_savings Conversion.bridge_arrival_tx) — that is an internal
  conversion, not a deposit;
- the transaction hash has not already proven another row, and could not
  be the transfer behind any ramp-linked row (that money is counted by its
  ramp). Reservation is deliberately conservative: EVERY transfer matching a
  ramp-linked row is reserved, so an orphan can never take a ramp's money;
  the worst case is a genuine transfer left uncounted.

Each run also revokes existing proofs that stopped qualifying (the row was
linked to a ramp later, the hash became ramp-reserved or a bridge arrival,
the counterparty turned out to be a Confío wallet),
so asynchronous linking can never leave money counted twice.

Conservative by design (under-counting is acceptable, over-counting is not):
clawback transfers (asset-sender set) are never proof, and transfers that
only appear as inner transactions of an app call are reported as
'inner_transfer_unsupported' rather than proven.

Historical only: rows created on or after PROOF_CUTOFF are never proven.
The wallet on a row is whatever address the account registered, and the
legacy UpdateAccountAlgorandAddress / CreateUSDCDeposit mutations take it
without proof of control — so once this metric exists, anyone could pair a
stranger's public transfer with a fabricated row. Before the metric there
was nothing to gain by that, and Algorand is no longer supported, so the
cutoff loses no genuine activity.

Read-only against the chain; rerunnable (rows with proof are skipped).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

logger = logging.getLogger(__name__)

PROOF_WINDOW = timedelta(hours=24)
# The day direct transfers started counting in public (see module docstring).
PROOF_CUTOFF = datetime(2026, 9, 25, tzinfo=dt_timezone.utc)
USDC_UNITS = Decimal(10) ** 6
# Pages of 100 per lookup; a single wallet's same-amount transfers inside a
# 48h window never come close, so this only bounds a misbehaving indexer.
MAX_PAGES = 20


@dataclass
class ProofContext:
    usdc_asset_id: int
    confio_addresses: set[str]
    bridge_arrival_hashes: set[str]
    used_hashes: set[str]


def _configured_algorand_addresses() -> list[str]:
    """Confío's own contracts and service wallets: the application address of
    every configured ALGORAND_*_APP_ID (cUSD escrow — minting is a USDC
    transfer from the user to it —, payment, payroll, invites, presale,
    humanitarian, rewards…) and every Algorand address declared in settings
    (sponsor, treasuries). New apps are covered without editing this list."""
    from algosdk import encoding
    from algosdk.logic import get_application_address
    from django.conf import settings

    found = []
    config = dict(getattr(settings, 'BLOCKCHAIN_CONFIG', {}) or {})
    config.update({name: getattr(settings, name) for name in dir(settings) if name.isupper()})
    for name, value in config.items():
        if name.startswith('ALGORAND_') and name.endswith('_APP_ID'):
            try:
                app_id = int(value or 0)
            except (TypeError, ValueError):
                continue
            if app_id > 0:
                found.append(get_application_address(app_id))
        elif isinstance(value, str) and len(value.strip()) == 58 and encoding.is_valid_address(value.strip()):
            found.append(value.strip())
    return found


def _historical_actor_addresses() -> list[str]:
    """Wallets that ever acted AS a Confío account in our own records. Not
    every replacement path records the old address (legacy
    UpdateAccountAlgorandAddress overwrites it), so the history is the only
    complete registry of former Confío wallets."""
    from conversion.models import Conversion
    from ramps.models import RampTransaction
    from send.models import SendTransaction
    from usdc_transactions.models import USDCDeposit, USDCWithdrawal

    found = []
    for model in (USDCDeposit, USDCWithdrawal, RampTransaction, Conversion):
        found += model.objects.exclude(actor_address='').exclude(actor_address__isnull=True) \
            .values_list('actor_address', flat=True).distinct()
    found += SendTransaction.all_objects.exclude(sender_type='external') \
        .values_list('sender_address', flat=True).distinct()
    found += SendTransaction.all_objects.exclude(recipient_type='external') \
        .values_list('recipient_address', flat=True).distinct()
    return [a for a in found if a]


def internal_algorand_addresses() -> set[str]:
    """Every Algorand address that is Confío's own, normalized: live and
    soft-deleted accounts, retired addresses (wallet migration to BSC clears
    Account.algorand_address and keeps the old one only in
    RetiredWalletAddress), every wallet that ever acted as a Confío account
    in our records (covers replacements that recorded nothing), the sponsor,
    and Confío's contract/service addresses from settings."""
    from django.conf import settings
    from users.models import Account, RetiredWalletAddress

    raw = list(
        Account.all_objects.exclude(algorand_address__isnull=True).exclude(algorand_address='')
        .values_list('algorand_address', flat=True)
    )
    raw += list(RetiredWalletAddress.objects.filter(chain=RetiredWalletAddress.CHAIN_ALGORAND)
                .values_list('address', flat=True))
    raw.append(getattr(settings, 'ALGORAND_SPONSOR_ADDRESS', None) or '')
    raw += _configured_algorand_addresses()
    raw += _historical_actor_addresses()
    return {_norm(a) for a in raw if a}


def build_context(usdc_asset_id: int) -> ProofContext:
    from conversion.models import Conversion
    from ramps.models import DirectTransferProof

    arrivals = set(
        Conversion.objects.filter(conversion_type='from_savings')
        .exclude(bridge_arrival_tx__isnull=True).exclude(bridge_arrival_tx='')
        .values_list('bridge_arrival_tx', flat=True)
    )
    used = set(DirectTransferProof.objects.values_list('transaction_hash', flat=True))
    return ProofContext(usdc_asset_id, internal_algorand_addresses(), arrivals, used)


def _norm(address) -> str:
    return str(address or '').strip().upper()


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _candidate_transfers(indexer, ctx: ProofContext, wallet: str, role: str, created_at: datetime, units: int):
    """Every USDC transfer for the wallet in the window, following pages."""
    next_page = None
    for _ in range(MAX_PAGES):
        resp = indexer.search_transactions(
            address=wallet,
            address_role=role,
            asset_id=ctx.usdc_asset_id,
            txn_type='axfer',
            start_time=_rfc3339(created_at - PROOF_WINDOW),
            end_time=_rfc3339(created_at + PROOF_WINDOW),
            min_amount=max(units - 1, 0),
            max_amount=units + 1,
            limit=100,
            next_page=next_page,
        )
        yield from resp.get('transactions', []) or []
        next_page = resp.get('next-token')
        if not next_page:
            return
    raise RuntimeError('indexer pagination did not terminate')


def _endpoints(row, kind: str):
    """(wallet, counterparty, indexer role), normalized: legacy mutations
    stored client-supplied addresses verbatim, in any case."""
    if kind == 'deposit':
        return _norm(row.actor_address), _norm(row.source_address), 'receiver'
    return _norm(row.actor_address), _norm(row.destination_address), 'sender'


def _has_inner_match(tx, units: int, asset_id: int) -> bool:
    for inner in tx.get('inner-txns') or []:
        xfer = inner.get('asset-transfer-transaction') or {}
        if xfer.get('asset-id') == asset_id and int(xfer.get('amount') or 0) == units:
            return True
        if _has_inner_match(inner, units, asset_id):
            return True
    return False


def _matching_transfers(row, kind: str, indexer, ctx: ProofContext):
    """Transfers that match the row exactly (wallet, counterparty, units,
    window), whatever else is true of them."""
    wallet, counterparty, role = _endpoints(row, kind)
    units = int((Decimal(row.amount) * USDC_UNITS).to_integral_value())
    if not wallet or not counterparty or units <= 0:
        return
    for tx in _candidate_transfers(indexer, ctx, wallet, role, row.created_at, units):
        if _has_inner_match(tx, units, ctx.usdc_asset_id):
            yield None, None, units, counterparty  # reported, never proof
            continue
        xfer = tx.get('asset-transfer-transaction') or {}
        if xfer.get('asset-id') != ctx.usdc_asset_id or int(xfer.get('amount') or 0) != units:
            continue
        if xfer.get('sender'):
            continue  # clawback: the debited account is not the outer sender
        sender, receiver = _norm(tx.get('sender')), _norm(xfer.get('receiver'))
        if kind == 'deposit' and (receiver != wallet or sender != counterparty):
            continue
        if kind == 'withdrawal' and (sender != wallet or receiver != counterparty):
            continue
        round_time = tx.get('round-time')
        if not tx.get('id') or not round_time:
            continue
        confirmed_at = datetime.fromtimestamp(int(round_time), tz=dt_timezone.utc)
        if abs(confirmed_at - row.created_at) > PROOF_WINDOW:
            continue
        yield tx, confirmed_at, units, counterparty


def find_proof(row, kind: str, indexer, ctx: ProofContext) -> tuple[dict | None, str]:
    """(proof fields, reason). The proof is None when the row can't be proven.
    Excluded candidates are skipped, not final: another matching transfer in
    the window may still prove the row."""
    wallet, counterparty, _ = _endpoints(row, kind)
    if not wallet or not counterparty:
        return None, 'missing_address'
    if counterparty in ctx.confio_addresses:
        return None, 'internal_counterparty'
    if Decimal(row.amount) <= 0:
        return None, 'non_positive_amount'

    excluded = None
    for tx, confirmed_at, units, counterparty in _matching_transfers(row, kind, indexer, ctx):
        if tx is None:
            excluded = excluded or 'inner_transfer_unsupported'
            continue
        txid = tx['id']
        if txid in ctx.bridge_arrival_hashes:
            excluded = excluded or 'bridge_arrival'
            continue
        if txid in ctx.used_hashes:
            excluded = excluded or 'transfer_already_counted'
            continue
        return {
            'transaction_hash': txid,
            'amount': Decimal(units) / USDC_UNITS,
            'counterparty_address': counterparty,
            'confirmed_at': confirmed_at,
        }, 'verified'
    return None, excluded or 'no_matching_transfer'


def ramp_backed_transfers(indexer, ctx: ProofContext) -> set[str]:
    """Every transfer that could be the one behind a ramp-linked row. All
    matches, not the first: indexer results are newest-first, and taking one
    per row let a ramp claim a neighbour's transfer and free its own."""
    from usdc_transactions.models import USDCDeposit, USDCWithdrawal

    hashes: set[str] = set()
    # Any status: a ramp counts on ITS completion, and its linked USDC row may
    # still say PROCESSING — that transfer is the ramp's all the same.
    linked = dict(ramp_transaction__isnull=False, amount__gt=0)
    for kind, model in (('deposit', USDCDeposit), ('withdrawal', USDCWithdrawal)):
        for row in model.objects.filter(**linked).order_by('created_at'):
            hashes.update(tx['id'] for tx, *_ in _matching_transfers(row, kind, indexer, ctx) if tx)
    return hashes


def _revocable_proofs(ctx: ProofContext, ramp_hashes: set[str]):
    from django.db.models import Q
    from ramps.models import DirectTransferProof

    return DirectTransferProof.objects.filter(
        Q(transaction_hash__in=ramp_hashes)
        | Q(transaction_hash__in=ctx.bridge_arrival_hashes)
        | Q(counterparty_address__in=ctx.confio_addresses)
        | Q(usdc_deposit__ramp_transaction__isnull=False)
        | Q(usdc_withdrawal__ramp_transaction__isnull=False)
    )


def verify_direct_transfers(indexer, *, dry_run: bool = False) -> dict:
    """Prove every unproven direct USDC transfer that the metric would count.
    Returns reason counts; writes DirectTransferProof rows unless dry_run."""
    from django.conf import settings
    from django.db import IntegrityError, transaction
    from django.db.models import Q
    from ramps.models import DirectTransferProof
    from usdc_transactions.models import USDCDeposit, USDCWithdrawal

    ctx = build_context(int(settings.ALGORAND_USDC_ASSET_ID))
    ramp_hashes = ramp_backed_transfers(indexer, ctx)
    revocable_ids = set(_revocable_proofs(ctx, ramp_hashes).values_list('pk', flat=True))
    revoked = len(revocable_ids)
    if revoked and not dry_run:
        DirectTransferProof.objects.filter(pk__in=revocable_ids).delete()
    # A dry run simulates the revocation: those proofs neither hold their
    # hash nor keep their row out of matching, exactly as after a real run.
    ctx.used_hashes = set(
        DirectTransferProof.objects.exclude(pk__in=revocable_ids).values_list('transaction_hash', flat=True)
    ) | ramp_hashes
    common = dict(status='COMPLETED', is_deleted=False, ramp_transaction__isnull=True, amount__gt=0,
                  created_at__lt=PROOF_CUTOFF)
    unproven = Q(direct_proof__isnull=True) | Q(direct_proof__pk__in=revocable_ids)
    todo = [
        ('deposit', row) for row in
        USDCDeposit.objects.filter(unproven, **common).order_by('created_at')
    ] + [
        ('withdrawal', row) for row in
        USDCWithdrawal.objects.filter(unproven, **common).order_by('created_at')
    ]

    outcome: dict[str, int] = {}
    if ramp_hashes:
        outcome['ramp_transfers_reserved'] = len(ramp_hashes)
    if revoked:
        outcome['proofs_revoked'] = revoked
    for kind, row in todo:
        try:
            proof, reason = find_proof(row, kind, indexer, ctx)
        except Exception:  # noqa: BLE001 — one bad lookup must not stop the backfill
            logger.exception('direct transfer proof lookup failed for %s %s', kind, row.pk)
            proof, reason = None, 'lookup_error'
        outcome[reason] = outcome.get(reason, 0) + 1
        if proof is None:
            continue
        if dry_run:
            ctx.used_hashes.add(proof['transaction_hash'])
            continue
        link = {'usdc_deposit': row} if kind == 'deposit' else {'usdc_withdrawal': row}
        try:
            with transaction.atomic():
                DirectTransferProof.objects.create(kind=kind, **link, **proof)
        except IntegrityError:
            outcome['duplicate_hash'] = outcome.get('duplicate_hash', 0) + 1
            outcome['verified'] -= 1
            continue
        ctx.used_hashes.add(proof['transaction_hash'])
    return outcome
