"""Chain -> mirrors (spec 7.6). Reads account and factory events into
SmartAccountEvent (append-only), then applies each one to the mirror tables
in block order. Mirror state that reflects the chain is written here and
nowhere else.

Fail-closed rules: an unreadable range leaves the cursor where it was; an
event that cannot be applied stays unapplied and blocks the later events of
the same account (order matters), and is retried on the next run.

Isolation: anyone can call the factory's createAccount from any EOA. Only
accounts Confío knows (a SmartAccount row, or created in the same scan by an
owner that is a Confío personal wallet) have their logs stored, and one
account's stuck event never holds back another account's events.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import abi, chain, notifications
from .models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountCharge, SmartAccountClaim, SmartAccountEvent,
    SmartAccountForcedSale, SmartAccountForcedSaleLeg, SmartAccountPayout, SmartAccountPreparedAction,
    SmartAccountRule, SmartAccountRuleRun, SmartAccountScanCursor,
)

logger = logging.getLogger(__name__)

CURSOR_KEY = 'events'
MAX_BLOCKS_PER_RUN = 20_000
WAD = 10 ** 18


# ── derived state ───────────────────────────────────────────────────────

def derive_status(account: SmartAccount, now=None) -> tuple[str, str]:
    """(status, billing_status) per spec 4.5 from the mirrored fields. The
    time-dependent transitions (period end, notice end) need no event."""
    now = now or timezone.now()
    if account.inherited_at is not None:
        return 'inherited', 'current'
    if not account.plan:
        return 'none', 'current'
    lapsed = account.paid_until is None or now >= account.paid_until
    if account.cancel_requested_at is not None:
        return ('expired' if lapsed else 'cancel_pending'), 'current'
    if not lapsed:
        return 'active', 'current'
    if account.notice_started_at is None:
        return 'active', 'payment_due'
    if account.sale_allowed_at is not None and now >= account.sale_allowed_at:
        return 'active', 'sale_allowed'
    return 'active', 'notice'


def refresh_derived(account: SmartAccount, now=None) -> SmartAccount:
    status, billing = derive_status(account, now)
    if (status, billing) != (account.status, account.billing_status):
        SmartAccount.all_objects.filter(pk=account.pk).update(
            status=status, billing_status=billing, updated_at=timezone.now())
        account.status, account.billing_status = status, billing
    return account


def refresh_all_derived() -> None:
    for account in SmartAccount.objects.exclude(status__in=('none', 'inherited')):
        refresh_derived(account)


# ── scan ────────────────────────────────────────────────────────────────

def _cursor() -> int | None:
    row = SmartAccountScanCursor.objects.filter(key=CURSOR_KEY).first()
    return row.block_number if row else None


def _set_cursor(block: int) -> None:
    SmartAccountScanCursor.objects.update_or_create(key=CURSOR_KEY, defaults={'block_number': int(block)})


def _confio_owner(owner: str) -> bool:
    """The owner of an AccountCreated is a live Confío personal wallet."""
    from users.models import Account
    return Account.objects.filter(bsc_address__iexact=owner, account_type='personal',
                                  deleted_at__isnull=True).exists()


def _store_logs(logs: list, factory: str, accounts: dict, times: dict, allowed: set | None = None) -> list:
    """Persist decoded logs; returns addresses of accounts created in them by
    a Confío owner. An account log is stored only for an address with a
    SmartAccount row (`accounts`) or one in `allowed` (created in this scan
    by a Confío owner); anything else is someone else's contract."""
    created = []
    allowed = allowed or set()
    for log in logs:
        address = (log.get('address') or '').lower()
        is_factory = address == factory
        if not is_factory and address not in accounts and address not in allowed:
            continue
        try:
            decoded = abi.decode_log(log, factory=is_factory)
        except Exception as exc:  # noqa: BLE001 — a log we cannot read is not skipped silently
            raise chain.ChainError(f'undecodable log {log.get("transactionHash")}') from exc
        if decoded is None:
            continue  # an event this ABI does not know (e.g. OZ Initialized)
        name, args = decoded
        if log.get('removed'):
            continue
        block_number = int(log['blockNumber'], 16)
        if block_number not in times:
            times[block_number] = chain.block_time(block_number)
        block_time, block_hash = times[block_number]
        SmartAccountEvent.objects.get_or_create(
            tx_hash=(log['transactionHash'] or '').lower(), log_index=int(log['logIndex'], 16),
            defaults={
                'smart_account': accounts.get(address), 'address': address, 'name': name, 'args': args,
                'block_number': block_number, 'block_hash': block_hash, 'block_time': block_time,
            })
        if is_factory and name == 'AccountCreated':
            if _confio_owner(args['owner']):
                created.append(args['account'].lower())
            else:
                logger.warning('smart account %s created by non-Confío owner %s: its logs are not read',
                               args['account'], args['owner'])
    return created


# Per-address log coverage, for an address whose logs are NOT continuously
# read with the global cursor: an account whose AccountCreated is stored but
# not applied yet (no row), and a row created without its logs having been
# read since its creation block. The value is the last block through which
# that address's logs are known to be stored. A row with no coverage key is
# read with the global cursor and is fully covered.
_COVERAGE_PREFIX = 'a:'


def _coverage_key(address: str) -> str:
    # SmartAccountScanCursor.key is 40 chars: 'a:' + the first 38 hex digits.
    return _COVERAGE_PREFIX + address.lower()[2:40]


def _coverage(addresses) -> dict:
    """{address: covered-through block} for the given addresses that have a
    coverage key."""
    keys = {_coverage_key(a): a for a in addresses}
    if not keys:
        return {}
    return {keys[row.key]: row.block_number
            for row in SmartAccountScanCursor.objects.filter(key__in=list(keys))}


def _set_coverage(address: str, block: int) -> None:
    SmartAccountScanCursor.objects.update_or_create(
        key=_coverage_key(address), defaults={'block_number': int(block)})


def _drop_coverage(addresses) -> None:
    if addresses:
        SmartAccountScanCursor.objects.filter(key__in=[_coverage_key(a) for a in addresses]).delete()


def _creating_addresses(factory: str) -> set:
    """Accounts whose AccountCreated is stored but not applied yet."""
    out = {str((args or {}).get('account') or '').lower() for args in SmartAccountEvent.objects.filter(
        address=factory, name='AccountCreated', applied_at__isnull=True).values_list('args', flat=True)}
    out.discard('')
    return out


def _creating_confio(factory: str, accounts: dict) -> set:
    """Stored-unapplied AccountCreated accounts of a Confío owner that have no
    row yet: their logs are read with the factory's until the row appears,
    so nothing they emit meanwhile is lost."""
    out = set()
    for event in SmartAccountEvent.objects.filter(address=factory, name='AccountCreated', applied_at__isnull=True):
        address = str((event.args or {}).get('account') or '').lower()
        if address and address not in accounts and _confio_owner((event.args or {}).get('owner') or ''):
            out.add(address)
    return out


def backfill_pending(addresses=None) -> set:
    """Rows whose logs are not yet known stored up to the global cursor
    (created without their logs having been read since their creation
    block). Their events are not applied until the backfill catches up:
    per-account order matters."""
    cursor = _cursor()
    if cursor is None:
        return set()
    lagging = SmartAccountScanCursor.objects.filter(key__startswith=_COVERAGE_PREFIX, block_number__lt=cursor)
    if addresses is not None:
        lagging = lagging.filter(key__in=[_coverage_key(a) for a in addresses])
    keys = set(lagging.values_list('key', flat=True))
    if not keys:
        return set()
    rows = SmartAccount.all_objects.values_list('contract_address', flat=True)
    if addresses is not None:
        rows = rows.filter(contract_address__in=[a.lower() for a in addresses])
    return {a.lower() for a in rows if _coverage_key(a) in keys}


def _backfill(accounts: dict, factory: str, upto: int, times: dict) -> None:
    """Re-read each lagging row's own logs from where its coverage ends (its
    creation block at the latest) up to `upto`, the block the global scan
    already passed. Bounded per run; the rest continues next run."""
    for address, covered in _coverage(accounts).items():
        if covered >= upto:
            continue
        start = covered + 1
        end = min(upto, covered + MAX_BLOCKS_PER_RUN)
        _store_logs(chain.get_logs([address], start, end), factory, accounts, times, allowed={address})
        _set_coverage(address, end)


def scan_events() -> dict:
    """Read new finalized logs of the factory and every known account."""
    factory = chain.factory_address()
    if not factory:
        return {'skipped': 'not_configured'}
    finalized = chain.finalized_block()
    cursor = _cursor()
    if cursor is None:
        start = int(getattr(settings, 'SMART_ACCOUNT_START_BLOCK', 0) or 0)
        cursor = (start - 1) if start > 0 else finalized
        _set_cursor(cursor)
    from_block = cursor + 1
    to_block = min(finalized, cursor + MAX_BLOCKS_PER_RUN)
    if to_block < from_block:
        return {'from': from_block, 'to': to_block, 'stored': 0}

    accounts = {a.contract_address.lower(): a for a in SmartAccount.all_objects.all()}
    before = SmartAccountEvent.objects.count()
    times: dict = {}
    # 1. Rows created without continuous coverage: their own past logs first.
    _backfill(accounts, factory, cursor, times)
    # 2. The new range: factory, every row, and every account whose
    #    AccountCreated is stored but not applied yet (its row may appear
    #    later; what it emits meanwhile must not be lost).
    creating = _creating_confio(factory, accounts)
    logs = chain.get_logs([factory] + list(accounts) + sorted(creating), from_block, to_block)
    created = _store_logs(logs, factory, accounts, times, allowed=creating)
    # An account created in this range emitted its own events (Subscribed in
    # the very same transaction) before we knew its address: read them now.
    fresh = [a for a in created if a not in accounts and a not in creating]
    if fresh:
        _store_logs(chain.get_logs(fresh, from_block, to_block), factory, accounts, times, allowed=set(fresh))
    # 3. Coverage bookkeeping. A rowless account is covered contiguously only
    #    when it was read from its creation range on (fresh now, or already
    #    keyed); one that was not gets no key, and its row is backfilled from
    #    its creation block when it appears (_account_created).
    known = _coverage(creating | set(fresh))
    for address in set(fresh) | {a for a in creating if a in known}:
        _set_coverage(address, to_block)
    # A row whose coverage reached the global cursor is read with it from now on.
    _drop_coverage([a for a, block in _coverage(accounts).items() if block >= cursor])
    # Keys of addresses that are neither a row nor still being created.
    keep = {_coverage_key(a) for a in set(accounts) | creating | set(fresh)}
    stale = [k for k in SmartAccountScanCursor.objects.filter(key__startswith=_COVERAGE_PREFIX)
             .values_list('key', flat=True) if k not in keep]
    if stale:
        SmartAccountScanCursor.objects.filter(key__in=stale).delete()
    _set_cursor(to_block)
    return {'from': from_block, 'to': to_block, 'stored': SmartAccountEvent.objects.count() - before}


def _pending_events(blocked: set, skipped: set):
    """Unapplied events in chain order, restricted IN THE QUERY (before any
    limit) to addresses that can be applied: the factory, an address with a
    SmartAccount row, or one whose AccountCreated is still pending; minus
    the addresses blocked by a failure in this run. A rowless address's
    events are never applied and so must never fill the window."""
    from django.db.models import Q
    factory = chain.factory_address()
    creating = _creating_addresses(factory)
    known = SmartAccount.all_objects.values('contract_address')
    qs = SmartAccountEvent.objects.filter(applied_at__isnull=True).filter(
        Q(address=factory) | Q(address__in=known) | Q(address__in=creating))
    if blocked:
        qs = qs.exclude(address__in=blocked)
    if skipped:
        qs = qs.exclude(pk__in=skipped)
    return qs.order_by('block_number', 'log_index')


def _block_key(event) -> str:
    """Ordering is per account. A factory AccountCreated belongs to the
    account it creates (a failure there must not hold back every other
    account's creation); other factory events share the factory's key."""
    if event.address == chain.factory_address() and event.name == 'AccountCreated':
        return str((event.args or {}).get('account') or '').lower() or event.address
    return event.address


def apply_pending(limit: int = 500, max_batches: int = 20) -> dict:
    """Apply stored events in order. An event that fails blocks only the
    later events of the same account; the next window is read without that
    account, so one stuck account can never stall the others."""
    # Rows still being backfilled wait (not a failure): an older event of
    # theirs may not be stored yet.
    blocked, skipped, applied, failed = set(backfill_pending()), set(), 0, 0
    # Accounts whose AccountCreated was applied without producing a row in
    # this run (a non-Confío owner): their events are never applicable.
    ignored = set()
    for _ in range(max_batches):
        pending = list(_pending_events(blocked | ignored, skipped)[:limit])
        if not pending:
            break
        for event in pending:
            key = _block_key(event)
            if event.address in blocked or key in blocked or event.address in ignored:
                continue
            try:
                with transaction.atomic():
                    locked = SmartAccountEvent.objects.select_for_update().get(pk=event.pk)
                    if locked.applied_at is not None:
                        continue
                    effects = apply_event(locked) or []
                    locked.applied_at = timezone.now()
                    locked.save(update_fields=['applied_at', 'smart_account'])
                applied += 1
                if key != event.address and locked.smart_account_id is None:
                    ignored.add(key)   # created by someone else: no row, nothing to apply
                elif key != event.address and backfill_pending({key}):
                    blocked.add(key)   # its past logs are read first (next scan)
            except Exception:  # noqa: BLE001 — stays unapplied, retried next run
                logger.exception('smart account event %s could not be applied', event)
                blocked.add(key)
                if key != event.address:
                    skipped.add(event.pk)  # a factory event: skip it, not the factory
                else:
                    blocked.add(event.address)
                failed += 1
                continue
            # Notifications and entitlements only after the mirror committed.
            for effect in effects:
                notifications.safe(effect)
        if len(pending) < limit:
            break
    if failed:
        _alert_stuck_events()
    return {'applied': applied, 'failed': failed}


def _alert_stuck_events() -> None:
    cutoff = timezone.now() - timedelta(minutes=30)
    stuck = SmartAccountEvent.objects.filter(applied_at__isnull=True, created_at__lt=cutoff).count()
    if not stuck:
        return
    from config.ops_alerts import send_ops_alert
    send_ops_alert(f'Cuenta inteligente: {stuck} eventos sin aplicar hace más de 30 min',
                   dedupe_key='smart_account_stuck_events', dedupe_seconds=3600)


def reconcile() -> dict:
    out = {'scan': scan_events()}
    out['apply'] = apply_pending()
    refresh_all_derived()
    return out


# ── apply ───────────────────────────────────────────────────────────────

def _dt(value):
    return chain.to_dt(int(value))


def _account_for(event) -> SmartAccount | None:
    if event.smart_account_id:
        return SmartAccount.all_objects.select_for_update().get(pk=event.smart_account_id)
    account = SmartAccount.all_objects.select_for_update().filter(contract_address=event.address).first()
    if account is not None:
        event.smart_account = account
    return account


def _action_for_tx(tx_hash: str, target: str):
    return (SmartAccountPreparedAction.objects
            .filter(sponsored_batch__tx_hash__iexact=tx_hash, target_address=target).order_by('-id').first())


def apply_event(event) -> list:
    """Apply one event to the mirrors. Returns callables to run after commit
    (notifications). Raises to leave the event unapplied."""
    if event.address == chain.factory_address():
        return _apply_factory(event)
    account = _account_for(event)
    if account is None:
        # Events of an account whose AccountCreated is not applied yet.
        raise RuntimeError(f'no account row for {event.address}')
    handler = _HANDLERS.get(event.name)
    effects = handler(account, event) if handler else []
    refresh_derived(account, now=timezone.now())
    return effects or []


def _apply_factory(event) -> list:
    if event.name == 'AccountCreated':
        return _account_created(event)
    if event.name == 'FeeScheduled':
        return _fee_scheduled(event)
    return []


def _account_created(event) -> list:
    from users.models import Account
    owner, address = event.args['owner'], event.args['account']
    existing = SmartAccount.all_objects.filter(contract_address=address).first()
    if existing is not None:
        event.smart_account = existing
        return []
    owner_account = Account.objects.filter(
        bsc_address__iexact=owner, account_type='personal', deleted_at__isnull=True).select_related('user').first()
    if owner_account is None:
        # Created on chain by an address that is not a Confío personal wallet.
        logger.warning('smart account %s created by unknown owner %s', address, owner)
        return []
    user = owner_account.user
    account_row = _own_account_row(user, address)
    smart = SmartAccount.objects.create(
        owner_user=user, owner_account=owner_account, account=account_row, contract_address=address,
        status='none', created_tx=event.tx_hash, created_block=event.block_number)
    event.smart_account = smart
    SmartAccountPreparedAction.objects.filter(
        target_address=address, smart_account__isnull=True, user=user).update(smart_account=smart)
    if not _coverage([address]):
        # Its logs were not read from its creation block on (the owner was
        # not a Confío wallet at scan time, say): re-read them from there
        # before any of its events is applied.
        _set_coverage(address, int(event.block_number) - 1)
    return []


def _own_account_row(user, address: str):
    """The users.Account 'smart' row at index 0 (the app's smart_0, the
    user's own account) for a newly created account.

    A soft-deleted index-0 row that no SmartAccount points at any more is
    the user's previous own account, inherited away (its heir got a row of
    their own): it keeps its address and history and moves to the next free
    index, so the new account takes index 0. That is the legitimate re-open
    (decision 33): the factory deploys a new account for an owner only once
    their current one is inherited, so it is not alerted.

    A live index-0 row whose account the chain already shows inherited (or
    owned by someone else) is the same re-open with a ClaimExecuted the
    mirror has not applied yet: the event waits, unalerted, and applies once
    that claim is mirrored. Anything else at index 0 is a second own account
    and is refused (the event stays unapplied, alerted)."""
    from users.models import Account
    rows = Account.all_objects.select_for_update().filter(user=user, account_type='smart')
    current = rows.filter(account_index=0).first()
    if current is not None and (current.bsc_address or '').lower() == address and current.deleted_at is None:
        return current
    if current is not None:
        linked = SmartAccount.all_objects.filter(account=current).select_related('owner_account').first()
        if (current.deleted_at is None or (current.bsc_address or '').lower() == address
                or linked is not None):
            passed = _passed_on_chain(linked) if (current.bsc_address or '').lower() != address else False
            if passed is not False:
                # True: a re-open the mirror lags on. None: unreadable, so
                # retried next run (the stuck-event sweep alerts if it lasts).
                raise RuntimeError(f'user {user.pk}: previous account {linked.contract_address} '
                                   f'{"inherited on chain, ClaimExecuted not mirrored yet" if passed else "unreadable"}')
            # Not convergeable without breaking "one own account per user"
            # (smart_account_one_own_per_user): it blocks only THIS new
            # account (factory events are keyed per created account) and
            # goes to ops right away rather than after the stuck-event sweep.
            _ops_alert(f'Cuenta inteligente: AccountCreated {address} para el usuario {user.pk}, que ya tiene '
                       f'otra Cuenta inteligente propia. Revisión manual.', f'smart_second_own_{address}')
            raise RuntimeError(f'user {user.pk} already has a different smart account row')
        taken = set(rows.values_list('account_index', flat=True))
        index = max(taken) + 1
        Account.all_objects.filter(pk=current.pk).update(account_index=index)
    return Account.objects.create(user=user, account_type='smart', account_index=0, bsc_address=address)


def _passed_on_chain(account) -> bool | None:
    """True when the chain shows `account` inherited, or owned by someone
    other than the wallet the mirror names (a ClaimExecuted not applied
    yet); False when the chain still names that wallet (or there is no
    account); None when unreadable."""
    if account is None or account.status == 'inherited':
        return account is not None
    signer = (getattr(account.owner_account, 'bsc_address', '') or '').lower()
    try:
        state = chain.account_control(account.contract_address)
        owner = str(state['owner'] or '').lower()
        if not int(owner or '0x0', 16):
            return None
    except Exception:  # noqa: BLE001
        logger.warning('smart account %s: owner()/inherited() unreadable', account.contract_address, exc_info=True)
        return None
    return bool(state['inherited']) or owner != signer


def _fee_scheduled(event) -> list:
    plan = abi.PLAN_KEYS.get(int(event.args['plan']))
    if plan is None:
        return []
    from django.core.cache import cache
    cache.delete('smart_account_factory_prices_v1')
    price = format((Decimal(event.args['newFeeUsd']) / Decimal(WAD)).quantize(Decimal('0.01')), 'f')
    effective = _dt(event.args['effectiveAt'])
    label = 'anual' if plan == 'annual' else 'mensual'
    effects = []
    for account in SmartAccount.objects.filter(status__in=('active', 'cancel_pending')):
        renewal_plan = account.next_plan or account.plan
        if renewal_plan == plan and account.cancel_requested_at is None:
            user = account.owner_user
            effects.append(lambda u=user: notifications.price_change_scheduled(u, label, price, effective))
    return effects


def _subscribed(account, event):
    account.plan = abi.PLAN_KEYS[int(event.args['plan'])]
    account.next_plan = ''
    account.paid_until = _dt(event.args['paidUntil'])
    account.cancel_requested_at = None
    account.notice_started_at = None
    account.sale_allowed_at = None
    account.forced_sale_for_period = None
    account.returned_notified_at = None
    account.save()
    from . import funnel
    user, plan, key = account.owner_user, account.plan, event.tx_hash
    return [lambda: funnel.record(user, 'subscribed', plan=plan, key=key)]


def _plan_changed(account, event):
    account.next_plan = abi.PLAN_KEYS.get(int(event.args['nextPlan']), '')
    account.save(update_fields=['next_plan', 'updated_at'])
    return []


def _cancelled(account, event):
    account.cancel_requested_at = event.block_time
    account.save(update_fields=['cancel_requested_at', 'updated_at'])
    from . import funnel
    user, plan, key = account.owner_user, account.plan, event.tx_hash
    return [lambda: notifications.cancellation_signed(account),
            lambda: funnel.record(user, 'cancelled', plan=plan, key=key)]


def _cancel_undone(account, event):
    account.cancel_requested_at = None
    account.save(update_fields=['cancel_requested_at', 'updated_at'])
    return []


def _fee_collected(account, event):
    args = event.args
    plan = abi.PLAN_KEYS[int(args['plan'])]
    cusd, shares = int(args['cusdAmount']), int(args['cusdPlusShares'])
    sold = SmartAccountEvent.objects.filter(
        tx_hash=event.tx_hash, name='ForcedSale', address=event.address).exists()
    paid_with = 'sale' if sold else 'mixed' if (cusd and shares) else 'cusd_plus' if shares else 'cusd'
    account.plan = plan
    account.next_plan = ''
    account.paid_until = _dt(args['paidUntil'])
    account.notice_started_at = None
    account.sale_allowed_at = None
    account.last_due_notice_at = None
    account.sale_eve_notified_for = None
    account.save()
    charge, created = SmartAccountCharge.objects.get_or_create(event=event, defaults={
        'smart_account': account, 'plan': plan, 'period_start': event.block_time,
        'period_end': account.paid_until, 'fee_usd': Decimal(args['feeUsd']) / Decimal(WAD),
        'cusd_amount': str(cusd), 'cusd_plus_shares': str(shares), 'p_plus': str(args['pPlus']),
        'paid_with': paid_with, 'tx_hash': event.tx_hash, 'charged_at': event.block_time,
    })
    if not created:
        return []
    from . import entitlements

    def _after():
        entitlements.sync_account(account)
        if paid_with == 'sale':
            notifications.forced_sale_done(account, charge)
        else:
            notifications.fee_collected(account, charge)
    return [_after]


def _notice_started(account, event):
    account.notice_started_at = event.block_time
    account.sale_allowed_at = _dt(event.args['saleAllowedAt'])
    account.save(update_fields=['notice_started_at', 'sale_allowed_at', 'updated_at'])
    sale_at = account.sale_allowed_at

    def _after():
        from .automation import sale_candidate_symbols
        notifications.payment_notice_started(account, sale_at, sale_candidate_symbols(account))
    return [_after]


def _forced_sale(account, event):
    args = event.args
    period = _dt(args['forPeriod'])
    account.forced_sale_for_period = period
    account.save(update_fields=['forced_sale_for_period', 'updated_at'])
    sale, _ = SmartAccountForcedSale.objects.get_or_create(
        smart_account=account, period_end=period, defaults={'notice_started_at': account.notice_started_at})
    previous = int(sale.dollars_out or 0) if sale.tx_hash == event.tx_hash else 0
    sale.status = 'succeeded'
    sale.tx_hash = event.tx_hash
    sale.dollars_out = str(previous + int(args['dollarsOut']))
    sale.save()
    leg = sale.legs.filter(asset__iexact=args['tokenIn']).order_by('-attempt').first()
    if leg is not None:
        leg.amount_in, leg.dollars_out = str(args['amountIn']), str(args['dollarsOut'])
        leg.save(update_fields=['amount_in', 'dollars_out'])
    else:
        SmartAccountForcedSaleLeg.objects.create(
            forced_sale=sale, attempt=max(sale.attempts, 1), position=sale.legs.count(),
            asset=args['tokenIn'], amount_in=str(args['amountIn']), dollars_out=str(args['dollarsOut']))
    return []


def _balances_changed(account, event):
    from . import inflight
    address = account.contract_address
    block = event.block_number
    return [lambda: inflight.invalidate_address(address, min_block=block)]


def _rule_from_chain(account, onchain_id: int, rule: SmartAccountRule | None, draft: SmartAccountRule | None,
                     *, keep_slot=None):
    """Write the mirror of one rule from the contract's own storage.
    `keep_slot` (an edit): the calendar slot the rule had; the edited rule's
    slot is never moved earlier than it (an edit prepared before a run and
    signed after it must not run the rule again)."""
    from users.models import Account
    data = chain.account_rule(account.contract_address, onchain_id)
    source = draft or rule
    # Snapshot the off-chain attributes BEFORE the reset below: `source` is
    # often the very row being written (a draft, or the row keeping its id).
    carried = None if source is None else {
        'payout_method': source.payout_method, 'payout_ref': source.payout_ref, 'payout_rail': source.payout_rail,
        'pagomovil_destination': source.pagomovil_destination,
        'standing_authorization': source.standing_authorization, 'amount': source.amount,
        'frequency': source.frequency}
    if rule is None:
        rule = draft or SmartAccountRule(smart_account=account)
    rule.onchain_id = onchain_id
    rule.state = 'onchain' if data['active'] else 'cancelled'
    rule.kind = data['kind']
    rule.frequency = data['frequency']
    rule.token_in = data['token_in']
    rule.token_out = data['token_out'] if int(data['token_out'], 16) else ''
    rule.amount = (Decimal(data['amount_usd_wei']) / Decimal(WAD)).quantize(Decimal('0.01'))
    rule.next_run_at = chain.to_dt(data['next_run_at'])
    rule.scheduled_for = rule.next_run_at
    if keep_slot is not None and (rule.scheduled_for is None or keep_slot > rule.scheduled_for):
        rule.scheduled_for = keep_slot
    rule.replaces = None
    rule.active = bool(data['active'])
    rule.deactivated_reason = ''
    rule.payee_address = data['payee'] if int(data['payee'], 16) else ''
    rule.payout_ref = data['payout_ref'] if int(data['payout_ref'], 16) else ''
    # Off-chain attributes come from the draft the owner prepared, and only
    # when it describes the SAME rule that is on chain.
    rule.payee_user = None
    rule.payout_method = None
    rule.pagomovil_destination = None
    rule.payout_rail = ''
    rule.standing_authorization = None
    rule.asset_key = ''
    if rule.kind == 'send':
        payee = Account.objects.filter(bsc_address__iexact=rule.payee_address, account_type='personal',
                                       deleted_at__isnull=True).first() if rule.payee_address else None
        rule.payee_user = payee.user if payee else None
        from .payouts import send_authorization_problem
        if carried is not None and carried['standing_authorization'] is not None:
            rule.standing_authorization = carried['standing_authorization']
        if send_authorization_problem(rule, data) is not None:
            # A send rule nobody authorized with Face, for these exact terms,
            # through Confío is never run.
            rule.standing_authorization = None
            rule.active = False
            rule.deactivated_reason = 'no_standing_authorization'
    elif rule.kind == 'payout':
        if (carried is not None
                and (carried['payout_method'] is not None or carried['pagomovil_destination'] is not None)
                and carried['payout_ref'] == rule.payout_ref
                and carried['amount'] == rule.amount and carried['frequency'] == rule.frequency):
            rule.payout_method = carried['payout_method']
            rule.pagomovil_destination = carried['pagomovil_destination']
            rule.payout_rail = carried['payout_rail']
            rule.standing_authorization = carried['standing_authorization']
        else:
            # A payment rule nobody authorized through Confío is never run.
            rule.active = False
            rule.deactivated_reason = 'no_standing_authorization'
    elif rule.kind == 'buy':
        rule.asset_key = _asset_key_for(rule.token_out)
    rule.deleted_at = None
    rule.save()
    return rule


def _asset_key_for(token: str) -> str:
    from cusd_plus import crypto_catalog
    from .assets import stock_by_address
    crypto = crypto_catalog.by_address(token, include_unlisted=True)
    if crypto is not None:
        return f'crypto:{crypto.symbol}'
    stock = stock_by_address(token)
    return f'stock:{stock[0]}' if stock else ''


def _draft_rule(event, account, key: str):
    action = _action_for_tx(event.tx_hash, account.contract_address)
    pk = (action.payload or {}).get(key) if action is not None else None
    return SmartAccountRule.all_objects.filter(pk=pk, smart_account=account).first() if pk else None


def _rule_created(account, event):
    onchain_id = int(event.args['id'])
    existing = SmartAccountRule.all_objects.filter(smart_account=account, onchain_id=onchain_id).first()
    draft = _draft_rule(event, account, 'rule_pk')
    if draft is not None and draft.state != 'draft':
        draft = None
    _rule_from_chain(account, onchain_id, existing, draft)
    from . import funnel
    user, plan = account.owner_user, account.plan
    return [lambda: funnel.record(user, 'rule_created', plan=plan)]


def _rule_updated(account, event):
    onchain_id = int(event.args['id'])
    existing = SmartAccountRule.all_objects.filter(smart_account=account, onchain_id=onchain_id).first()
    draft = _draft_rule(event, account, 'rule_pk')
    if draft is not None and (draft.state != 'draft' or draft.pk == getattr(existing, 'pk', None)):
        draft = None
    old_authorization = existing.standing_authorization if existing is not None else None
    keep_slot = existing.scheduled_for if existing is not None and existing.state == 'onchain' else None
    if existing is not None and draft is not None:
        # Carry the draft's off-chain attributes onto the row that keeps the id.
        for name in ('payout_method', 'pagomovil_destination', 'payout_ref', 'payout_rail', 'standing_authorization',
                     'amount', 'frequency'):
            setattr(existing, name, getattr(draft, name))
        rule = _rule_from_chain(account, onchain_id, existing, existing, keep_slot=keep_slot)
        draft.replaces = None
        draft.deleted_at = timezone.now()
        draft.save(update_fields=['replaces', 'deleted_at'])
    else:
        rule = _rule_from_chain(account, onchain_id, existing, draft, keep_slot=keep_slot)
    if old_authorization is not None and old_authorization.pk != getattr(rule.standing_authorization, 'pk', None):
        _revoke(old_authorization, 'rule_updated')
    return []


def _revoke(authorization, reason: str) -> None:
    type(authorization).objects.filter(pk=authorization.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=reason)


def _rule_cancelled(account, event):
    rule = SmartAccountRule.all_objects.filter(smart_account=account, onchain_id=int(event.args['id'])).first()
    if rule is None:
        return []
    rule.active = False
    rule.state = 'cancelled'
    rule.save(update_fields=['active', 'state', 'updated_at'])
    if rule.standing_authorization is not None:
        _revoke(rule.standing_authorization, 'rule_cancelled')
    return []


def _rule_executed(account, event):
    args = event.args
    rule = SmartAccountRule.all_objects.filter(smart_account=account, onchain_id=int(args['id'])).first()
    if rule is None:
        return []
    gap = timedelta(days=abi.MIN_GAP_DAYS[rule.frequency])
    rule.next_run_at = event.block_time + gap
    rule.save(update_fields=['next_run_at', 'updated_at'])
    run = rule.runs.filter(tx_hash__iexact=event.tx_hash).first()
    if run is None:
        run = SmartAccountRuleRun.objects.create(
            rule=rule, scheduled_for=event.block_time, tx_hash=event.tx_hash, status='sent')
    if run.status == 'ok':
        return []
    run.status = 'ok'
    run.amount_in, run.amount_out = str(args['amountIn']), str(args['amountOut'])
    run.error = ''
    run.message = run.message or 'Listo.'
    run.save()
    from .automation import schedule_next
    schedule_next(rule, after=event.block_time)
    if rule.kind == 'payout':
        return []  # told at delivery, with the fiat amount (PayoutSent + provider)

    def _after():
        if SmartAccountRuleRun.objects.filter(pk=run.pk, notified_at__isnull=True).update(notified_at=timezone.now()):
            notifications.rule_run(run)
    return [_after]


# A payout the chain may still show paid: not yet seen sent, or given up.
_UNSENT_PAYOUT = ('reserving', 'prepared', 'pending', 'cancelled')


def _unmatched_payout(account, rule, event):
    """A PayoutSent whose transaction is not a run's recorded hash (the
    relayer's hash was lost or replaced, or RuleExecuted made a bare run for
    it). Matched by the bridge address the contract paid: the rule's one
    payout not yet seen sent whose deposit_address is that destination and
    whose run has no hash or this one: a run already holding another
    transaction's hash is that transaction's payout (an open one before a
    given-up one: Relay may reuse one route per source).
    The hash is attached to that payout's run so ramps can prove it. Anything
    else is ops', never silently dropped."""
    destination = str(event.args.get('destination') or '').lower()
    payout = None
    if rule is not None and destination:
        candidates = list(SmartAccountPayout.objects.select_related('rule_run').filter(
            rule_run__rule=rule, deposit_address__iexact=destination, status__in=_UNSENT_PAYOUT))
        # A run already carrying ANOTHER transaction's hash is that
        # transaction's payout (B prepared and submitted while A's late
        # PayoutSent arrives): never overwrite it with this event's hash.
        candidates = [p for p in candidates
                      if (p.rule_run.tx_hash or '').lower() in ('', event.tx_hash.lower())]
        for group in ([p for p in candidates if p.status != 'cancelled'],
                      [p for p in candidates if p.status == 'cancelled']):
            if group:
                payout = group[0] if len(group) == 1 else None
                break
    if payout is None:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: PayoutSent sin pago que le corresponda (cuenta {account.pk}, regla '
                       f'{_args_id(event)}, destino {destination or "?"}, tx {event.tx_hash}). Revisar a mano.',
                       dedupe_key=f'smart_payout_unmatched_{event.tx_hash}', dedupe_seconds=86400)
        return None
    run = payout.rule_run
    if (run.tx_hash or '').lower() != event.tx_hash.lower():
        logger.warning('PayoutSent %s matched payout %s by destination (run hash %r)',
                       event.tx_hash, payout.pk, run.tx_hash)
        SmartAccountRuleRun.objects.filter(pk=run.pk).update(tx_hash=event.tx_hash, updated_at=timezone.now())
        run.tx_hash = event.tx_hash
    return payout


def _args_id(event):
    try:
        return int(event.args.get('id'))
    except (TypeError, ValueError):
        return '?'


def _payout_sent(account, event):
    args = event.args
    rule = SmartAccountRule.all_objects.filter(smart_account=account, onchain_id=int(args['id'])).first()
    run = rule.runs.filter(tx_hash__iexact=event.tx_hash).first() if rule is not None else None
    payout = SmartAccountPayout.objects.filter(rule_run=run).first() if run is not None else None
    if payout is None:
        payout = _unmatched_payout(account, rule, event)
        if payout is None:
            return []
        run = payout.rule_run
    if payout.deposit_address and payout.deposit_address.lower() != args['destination']:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: PayoutSent a {args["destination"]} no coincide con el puente '
                       f'esperado (run {run.pk})', dedupe_key=f'smart_payout_dest_{run.pk}', dedupe_seconds=86400)
    payout.usdt_amount = str(args['usdtOut'])
    # 'cancelled' too: a payout given up (its order closed) that the chain
    # shows paid after all is on its way, and the mirror follows its ramp.
    revived = payout.status == 'cancelled'
    if payout.status in ('reserving', 'prepared', 'pending', 'cancelled'):
        payout.status = 'onchain_sent'
    payout.save(update_fields=['usdt_amount', 'status', 'updated_at'])
    if payout.ramp_id is None:
        return []
    _check_ramp_amount(payout, run, args)
    from . import payouts
    payout_pk, tx_hash = payout.pk, event.tx_hash
    effects = []
    if revived:
        # The owner was told this run did not happen: tell them it left.
        effects.append(lambda: notifications.safe(notifications.payout_resumed, run))
    # Pago Móvil: ramps proves this funding and pays the beneficiary.
    effects.append(lambda: payouts.after_payout_sent(payout_pk, tx_hash))
    return effects


def _check_ramp_amount(payout, run, args) -> None:
    """The contract takes usdtOut >= minUsdtOut; ramps waits for the exact
    deposit_wei it quoted the bridge for. Ops hear of any difference (more
    is still proven from the reported hash and recorded as excess; less is
    never proven)."""
    from ramps.models import RampTransaction
    try:
        ramp = RampTransaction.objects.get(pk=payout.ramp_id)
        expected = int(((ramp.metadata or {}).get('ve_send') or {}).get('deposit_wei'))
        sent = int(args['usdtOut'])
    except (RampTransaction.DoesNotExist, TypeError, ValueError, KeyError):
        expected, sent = None, None
    if expected is not None and sent == expected:
        return
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: PayoutSent usdtOut {args.get("usdtOut")} no coincide con el '
                       f'depósito del envío ({expected}) (run {run.pk}, payout {payout.pk})',
                       dedupe_key=f'smart_payout_amount_{run.pk}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('ops alert failed')


def _beneficiary_named(account, event):
    args = event.args
    address = args['pendingBeneficiary']
    action = _action_for_tx(event.tx_hash, account.contract_address)
    pk = (action.payload or {}).get('beneficiary_pk') if action is not None else None
    row = SmartAccountBeneficiary.objects.filter(pk=pk, smart_account=account).first() if pk else None
    if row is not None and (row.state != 'draft' or row.beneficiary_address.lower() != address):
        row = None
    if row is None:
        # The relay originates no designation it did not prepare; reaching
        # this branch means that guarantee was broken somewhere.
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Cuenta inteligente: BeneficiaryNamed sin designación preparada ({event.tx_hash})',
                       dedupe_key=f'smart_named_unprepared_{event.tx_hash}', dedupe_seconds=86400)
        named_user = _person_for_address(address)
        if named_user is None:
            # Whatever was pending before is replaced on chain all the same.
            SmartAccountBeneficiary.objects.filter(smart_account=account, state='pending_acceptance').update(
                state='removed', removed_at=event.block_time)
            return []
        row = SmartAccountBeneficiary(
            smart_account=account, beneficiary_user=named_user, beneficiary_address=address,
            verified_at_designation=False, residence_check='unchecked')
    SmartAccountBeneficiary.objects.filter(smart_account=account, state='pending_acceptance').exclude(
        pk=row.pk).update(state='removed', removed_at=event.block_time)
    row.challenge_window_seconds = int(args['challengeWindow'])
    row.designated_at = event.block_time
    row.designated_tx = event.tx_hash
    row.expires_at = _dt(args['expiresAt'])
    row.state = 'pending_acceptance'
    row.last_reminder_at = event.block_time
    row.save()
    from . import funnel
    user, plan = account.owner_user, account.plan
    return [lambda: notifications.beneficiary_named(row),
            lambda: funnel.record(user, 'beneficiary_set', plan=plan)]


def _ops_alert(message: str, key: str) -> None:
    """An alert from inside an event's transaction: it must never make the
    event fail (the mirror converging matters more than the message)."""
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(message, dedupe_key=key, dedupe_seconds=86400)
    except Exception:  # noqa: BLE001
        logger.exception('smart account ops alert failed: %s', message)


def _person_for_address(address: str):
    """The Confío user behind a personal wallet address: a live account
    first, then a closed one. None when Confío has no record of it."""
    from users.models import Account
    account = (Account.objects.filter(bsc_address__iexact=address, account_type='personal',
                                      deleted_at__isnull=True).select_related('user').first()
               or Account.all_objects.filter(bsc_address__iexact=address, account_type='personal')
               .select_related('user').order_by('-id').first())
    return account.user if account is not None else None


# Server-side states a designation can reach while its acceptance is on the
# wire (decline, lapse, wallet change). The chain is the truth: a mined
# BeneficiaryAccepted revives the row.
_ACCEPTABLE_STATES = ('pending_acceptance', 'declined', 'lapsed', 'stale_address')


def _repair_beneficiary_row(account, address: str, event, *, why: str):
    """The mirror has no row the chain's beneficiary event can apply to:
    the newest row for this address is reused, else one is created from the
    event. Ops is told either way. None only when no Confío user is behind
    the address at all (still alerted; the event is applied regardless)."""
    row = (SmartAccountBeneficiary.objects.filter(smart_account=account, beneficiary_address__iexact=address)
           .order_by('-id').first())
    if row is None:
        user = _person_for_address(address)
        if user is not None:
            row = SmartAccountBeneficiary.objects.create(
                smart_account=account, beneficiary_user=user, beneficiary_address=address.lower(),
                challenge_window_seconds=int(event.args.get('challengeWindow') or 0),
                verified_at_designation=False, residence_check='unchecked', state='pending_acceptance',
                designated_tx='')
    _ops_alert(f'Cuenta inteligente: {event.name} en {account.contract_address} sin designación espejo '
               f'({why}; {event.tx_hash}). ' + ('Espejo reparado desde la cadena.' if row is not None
                                                else 'Sin usuario Confío para esa billetera: revisión manual.'),
               f'smart_benef_repair_{event.tx_hash}_{event.log_index}')
    return row


def _beneficiary_accepted(account, event):
    address = event.args['beneficiary'].lower()
    row = (SmartAccountBeneficiary.objects.filter(
        smart_account=account, beneficiary_address__iexact=address, state__in=_ACCEPTABLE_STATES,
        accepted_at__isnull=True).order_by('-id').first())
    if row is not None and row.state != 'pending_acceptance':
        # Declined, lapsed or flagged by the server after the acceptance was
        # mined: the chain made this person the beneficiary.
        _ops_alert(f'Cuenta inteligente: BeneficiaryAccepted aplicado sobre una designación '
                   f'{row.state} ({account.contract_address}, {event.tx_hash}). Revivida como activa.',
                   f'smart_benef_revived_{event.tx_hash}')
    if row is None:
        row = _repair_beneficiary_row(account, address, event, why='sin designación pendiente')
    if row is None:
        # Still nobody to point it at: earlier rows of OTHER people are no
        # longer the beneficiary on chain.
        SmartAccountBeneficiary.objects.filter(
            smart_account=account, state__in=('pending_acceptance', 'active', 'stale_address')).update(
            state='removed', removed_at=event.block_time)
        return []
    effects = []
    previous = list(SmartAccountBeneficiary.objects.filter(
        smart_account=account, state__in=('active', 'stale_address')).exclude(pk=row.pk))
    for old in previous:
        same_person = old.beneficiary_address.lower() == address
        if same_person:
            # Re-named to change the window: standing and cooldown are kept.
            row.cooldown_until = old.cooldown_until
            SmartAccountClaim.objects.filter(beneficiary_row=old, state='pending').update(beneficiary_row=row)
        old.state = 'removed'
        old.removed_at = event.block_time
        old.save(update_fields=['state', 'removed_at', 'updated_at'])
        if not same_person:
            effects.append(lambda o=old: notifications.beneficiary_removed(o))
    row.state = 'active'
    row.accepted_at = event.block_time
    row.accepted_tx = event.tx_hash
    row.declined_at = None
    row.challenge_window_seconds = int(event.args['challengeWindow'])
    row.expires_at = None
    row.save()
    effects.append(lambda: notifications.beneficiary_accepted(row))
    return effects


def _designation_withdrawn(account, event):
    SmartAccountBeneficiary.objects.filter(
        smart_account=account, state='pending_acceptance',
        beneficiary_address__iexact=event.args['pendingBeneficiary'],
    ).update(state='removed', removed_at=event.block_time)
    return []


def _beneficiary_removed(account, event):
    effects = []
    rows = list(SmartAccountBeneficiary.objects.filter(
        smart_account=account, state__in=('pending_acceptance', 'active', 'stale_address')))
    for row in rows:
        was_active = row.state in ('active', 'stale_address')
        row.state = 'removed'
        row.removed_at = event.block_time
        row.save(update_fields=['state', 'removed_at', 'updated_at'])
        SmartAccountClaim.objects.filter(beneficiary_row=row, state='pending').update(
            state='cancelled', cancelled_at=event.block_time, cancelled_tx=event.tx_hash)
        if was_active:
            effects.append(lambda r=row: notifications.beneficiary_removed(r))
    return effects


def _active_row(account, address: str):
    return (SmartAccountBeneficiary.objects.filter(
        smart_account=account, beneficiary_address__iexact=address,
        state__in=('active', 'stale_address')).order_by('-id').first())


def _claim_initiated(account, event):
    address = event.args['beneficiary'].lower()
    row = _active_row(account, address)
    if row is None:
        # The mirror lost the accepted beneficiary (a row the server moved
        # on from, or never had): the chain says this address may claim, so
        # the row is repaired and the owner is told; never a stuck account.
        row = _repair_beneficiary_row(account, address, event, why='sin beneficiario aceptado')
        if row is not None:
            row.state = 'active'
            row.accepted_at = row.accepted_at or event.block_time
            row.removed_at = None
            row.declined_at = None
            row.expires_at = None
            if not row.challenge_window_seconds:
                row.challenge_window_seconds = max(
                    0, int(event.args['executableAt']) - int(event.block_time.timestamp()))
            row.save()
            # The chain has one beneficiary: nobody else's row stays accepted.
            SmartAccountBeneficiary.objects.filter(
                smart_account=account, state__in=('active', 'stale_address')).exclude(pk=row.pk).update(
                state='removed', removed_at=event.block_time)
    if row is None:
        # No Confío user behind it (alerted). The owner's batches still
        # carry cancelClaim: claim_pending_on_own_account reads the chain.
        return []
    claim, created = SmartAccountClaim.objects.get_or_create(initiated_tx=event.tx_hash, defaults={
        'beneficiary_row': row, 'initiated_at': event.block_time,
        'executable_at': _dt(event.args['executableAt']), 'state': 'pending',
        'last_owner_notice_at': event.block_time, 'owner_notices_sent': 1,
    })
    if not created:
        return []
    return [lambda: notifications.claim_initiated_owner(claim),
            lambda: notifications.claim_initiated_beneficiary(claim)]


def _claim_cancelled(account, event):
    address = event.args['beneficiary']
    claim = (SmartAccountClaim.objects.filter(
        beneficiary_row__smart_account=account, beneficiary_row__beneficiary_address__iexact=address,
        state='pending').order_by('-initiated_at').first())
    if claim is None:
        return []
    cooldown = int(event.args['cooldownUntil'])
    row = claim.beneficiary_row
    row.cooldown_until = _dt(cooldown) if cooldown else None
    row.save(update_fields=['cooldown_until', 'updated_at'])
    claim.state = 'cancelled'
    claim.cancelled_at = event.block_time
    claim.cancelled_tx = event.tx_hash
    claim.save(update_fields=['state', 'cancelled_at', 'cancelled_tx'])
    return [lambda: notifications.claim_cancelled(claim)]


def _new_owner_account(account, new_owner_address: str):
    """The personal users.Account of the wallet that now owns the account:
    a live one first, then a soft-deleted one (the beneficiary closed their
    app account; the chain still made them the owner). None when Confío has
    no record of the wallet at all."""
    from users.models import Account
    live = Account.objects.filter(bsc_address__iexact=new_owner_address, account_type='personal',
                                  deleted_at__isnull=True).select_related('user').first()
    if live is not None:
        return live, False
    closed = (Account.all_objects.filter(bsc_address__iexact=new_owner_address, account_type='personal')
              .select_related('user').order_by('-id').first())
    return closed, closed is not None


def _claim_executed(account, event):
    from users.models import Account
    from config.ops_alerts import send_ops_alert
    new_owner_address = event.args['newOwner']
    new_account, closed = _new_owner_account(account, new_owner_address)
    claim = (SmartAccountClaim.objects.filter(beneficiary_row__smart_account=account, state='pending')
             .order_by('-initiated_at').first())
    previous_owner = account.owner_user
    if claim is not None:
        claim.state = 'executed'
        claim.executed_at = event.block_time
        claim.executed_tx = event.tx_hash
        claim.save(update_fields=['state', 'executed_at', 'executed_tx'])
    _close_for_inheritance(account, event)
    if new_account is None:
        # The chain is the truth and this event must not block the account's
        # later events. Everything certain is mirrored: the account is
        # inherited (no plan, no rules, no fee, no IA+ for the previous
        # owner) and the previous owner no longer reaches it (their row is
        # closed). Only WHO the new owner is goes to ops: until then nobody
        # holds a row for it (account=None), so nobody can act on it here.
        old_row = account.account
        if old_row is not None:
            old_row.soft_delete()
        account.account = None
        account.inherited_from_user = previous_owner
        account.inherited_at = event.block_time
        account.save()
        send_ops_alert(f'Cuenta inteligente: ClaimExecuted de {account.contract_address} a una billetera sin '
                       f'cuenta en Confío ({new_owner_address}, {event.tx_hash}). Revisión manual del dueño.',
                       dedupe_key=f'smart_claim_unknown_owner_{event.tx_hash}', dedupe_seconds=86400)
        from . import entitlements
        return [lambda: entitlements.sync_user(previous_owner)]
    if closed:
        send_ops_alert(f'Cuenta inteligente: ClaimExecuted de {account.contract_address} a la cuenta cerrada '
                       f'del usuario {new_account.user_id} ({event.tx_hash}). Aplicado; revisar acceso.',
                       dedupe_key=f'smart_claim_closed_owner_{event.tx_hash}', dedupe_seconds=86400)
    new_owner = new_account.user
    # The users.Account row: the previous owner's is closed; the new owner
    # gets one at the next inherited index (1 and up, in order received).
    old_row = account.account
    if old_row is not None:
        old_row.soft_delete()
    taken = set(Account.all_objects.filter(user=new_owner, account_type='smart')
                .values_list('account_index', flat=True))
    index = 1
    while index in taken:
        index += 1
    new_row = Account.objects.create(
        user=new_owner, account_type='smart', account_index=index, bsc_address=account.contract_address)
    account.inherited_from_user = previous_owner
    account.inherited_at = event.block_time
    account.owner_user = new_owner
    account.owner_account = new_account
    account.account = new_row
    account.save()
    from . import entitlements

    def _after():
        entitlements.sync_user(previous_owner)
        notifications.claim_executed(account, previous_owner, new_owner)
    return [_after]


def _close_for_inheritance(account, event) -> None:
    """What a ClaimExecuted changes whoever the new owner is: designations
    end, rules stop (their payment authorizations are revoked), the plan and
    its billing state are gone. The caller saves `account`."""
    SmartAccountBeneficiary.objects.filter(
        smart_account=account, state__in=('draft', 'pending_acceptance', 'active', 'stale_address'),
    ).update(state='removed', removed_at=event.block_time)
    for rule in SmartAccountRule.all_objects.filter(smart_account=account):
        rule.active = False
        rule.state = 'cancelled'
        rule.deactivated_reason = 'inherited'
        rule.save(update_fields=['active', 'state', 'deactivated_reason', 'updated_at'])
        if rule.standing_authorization is not None:
            _revoke(rule.standing_authorization, 'inherited')
    account.inherited_at = event.block_time
    account.status = 'inherited'
    account.billing_status = 'current'
    account.plan = ''
    account.next_plan = ''
    account.paid_until = None
    account.cancel_requested_at = None
    account.notice_started_at = None
    account.sale_allowed_at = None
    account.forced_sale_for_period = None


def _confio_latched(account, event):
    account.confio_sale_latched = True
    account.save(update_fields=['confio_sale_latched', 'updated_at'])
    return []


_HANDLERS = {
    'Subscribed': _subscribed,
    'PlanChanged': _plan_changed,
    'SubscriptionCancelled': _cancelled,
    'CancelUndone': _cancel_undone,
    'FeeCollected': _fee_collected,
    'PaymentNoticeStarted': _notice_started,
    'ForcedSale': _forced_sale,
    'Withdrawn': _balances_changed,
    'AssetReturned': _balances_changed,
    'Traded': _balances_changed,
    'UsdtConverted': _balances_changed,
    'RuleCreated': _rule_created,
    'RuleUpdated': _rule_updated,
    'RuleCancelled': _rule_cancelled,
    'RuleExecuted': _rule_executed,
    'PayoutSent': _payout_sent,
    'BeneficiaryNamed': _beneficiary_named,
    'BeneficiaryAccepted': _beneficiary_accepted,
    'DesignationWithdrawn': _designation_withdrawn,
    'BeneficiaryRemoved': _beneficiary_removed,
    'ClaimInitiated': _claim_initiated,
    'ClaimCancelled': _claim_cancelled,
    'ClaimExecuted': _claim_executed,
    'ConfioSaleLatched': _confio_latched,
}
