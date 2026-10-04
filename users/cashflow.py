"""Month summary ("Tu mes") over the unified ledger.

Design: docs/designs/cashflow-home-tu-mes.md (eng R1/R2/R5/R6/R9/R11, C2/C9).

Reads exactly the rows the history list shows (account_unified_queryset), so
the month view and the history can never disagree about which movements
exist. Each row gets a rail-derived `kind`; kinds land in buckets:

  income  (Entró): income_person, sale, payroll_in, bonus
  spending (Salió): merchant, p2p_send, payroll_out, donation
  own lines:        top_up, withdrawal              (never in Entró/Salió)
  net lines:        savings_in/out, investment_in/out
  hidden:           own_transfer, conversion

Only CONFIRMED rows in USD tokens count; FAILED (incl. refunded local
transfers) drop out exactly as they do in history (R11). Amounts are the
viewer's side (amount_for_direction: payer gross, recipient net).
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USD_TOKENS = {'CUSD', 'CUSD_BSC', 'CUSD_PLUS', 'USDT', 'USDC'}

INCOME_KINDS = {'income_person', 'sale', 'payroll_in', 'bonus'}
SPENDING_KINDS = {'merchant', 'p2p_send', 'payroll_out', 'donation'}
COUNTERPARTY_KINDS = INCOME_KINDS | SPENDING_KINDS

# Device timezone is preferred (sent by the client); this is only the
# fallback when the client sends none or an invalid name.
TIMEZONE_BY_PHONE_COUNTRY = {
    'AR': 'America/Argentina/Buenos_Aires', 'BO': 'America/La_Paz',
    'BR': 'America/Sao_Paulo', 'CL': 'America/Santiago', 'CO': 'America/Bogota',
    'CR': 'America/Costa_Rica', 'DO': 'America/Santo_Domingo',
    'EC': 'America/Guayaquil', 'ES': 'Europe/Madrid', 'GT': 'America/Guatemala',
    'HN': 'America/Tegucigalpa', 'MX': 'America/Mexico_City',
    'NI': 'America/Managua', 'PA': 'America/Panama', 'PE': 'America/Lima',
    'PY': 'America/Asuncion', 'SV': 'America/El_Salvador',
    'US': 'America/New_York', 'UY': 'America/Montevideo', 'VE': 'America/Caracas',
}


def resolve_timezone(tz_name: str | None, phone_country: str | None) -> ZoneInfo:
    for candidate in (tz_name, TIMEZONE_BY_PHONE_COUNTRY.get((phone_country or '').upper())):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo('UTC')


def month_window(year: int, month: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(date(year, month, 1), time.min, tzinfo=tz)
    last = calendar.monthrange(year, month)[1]
    end = datetime.combine(date(year, month, last), time.min, tzinfo=tz) + timedelta(days=1)
    return start, end


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def comparison_window(year: int, month: int, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime, bool]:
    """Window to compare against: same period of the previous month while the
    viewed month is still running ("Mismo período de …"), else the full
    previous month ("vs … completo"). Returns (start, end, is_partial)."""
    py, pm = previous_month(year, month)
    p_start, p_end = month_window(py, pm, tz)
    local_now = now.astimezone(tz)
    if (local_now.year, local_now.month) != (year, month):
        return p_start, p_end, False
    # Same day number, clamped to the shorter month, up to the same time of day.
    day = min(local_now.day, calendar.monthrange(py, pm)[1])
    cutoff = datetime.combine(date(py, pm, day), local_now.timetz().replace(tzinfo=None), tzinfo=tz)
    return p_start, min(cutoff, p_end), True


CENT = Decimal('0.01')


def _viewer_amount(row, direction: str) -> Decimal | None:
    """Strict viewer-side amount: payer gross, recipient gross minus fee.
    Unlike the display helper, invalid monetary data raises instead of
    falling back to gross, so a bad row can't inflate the month."""
    gross = _decimal(row.amount)
    if gross is None or not gross.is_finite():
        raise SummaryUnavailable(f'unified {getattr(row, "pk", "?")}: invalid amount')
    if gross <= 0:
        return None
    if direction != 'received' or not row.fee_amount:
        return gross
    fee = _decimal(row.fee_amount)
    if fee is None or not fee.is_finite() or fee < 0 or fee > gross:
        raise SummaryUnavailable(f'unified {getattr(row, "pk", "?")}: invalid fee')
    return gross - fee


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _norm_id(value) -> str:
    return re.sub(r'[^0-9A-Z]', '', str(value or '').upper())


# KYC stores a canonical type ('national_id'); payout destinations store
# whatever the user's bank form called it. Same document, many names.
_DOC_TYPE_FAMILY = {
    'NATIONALID': 'national_id', 'DNI': 'national_id', 'CI': 'national_id',
    'CC': 'national_id', 'CEDULA': 'national_id', 'CEDULADEIDENTIDAD': 'national_id',
    'CEDULADECIUDADANIA': 'national_id', 'IDCARD': 'national_id', 'CIV': 'national_id',
    'INE': 'national_id', 'CURP': 'national_id', 'RG': 'national_id', 'CPF': 'tax_id',
    'RUT': 'national_id', 'RUN': 'national_id', 'DUI': 'national_id',
    'PASSPORT': 'passport', 'PASAPORTE': 'passport', 'PASSAPORTE': 'passport',
}


def _doc_family(value) -> str:
    # Fold accents first ('Cédula' -> 'CEDULA'), then keep letters only.
    folded = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
    key = re.sub(r'[^A-Z]', '', folded.upper())
    return _DOC_TYPE_FAMILY.get(key, key)


def _norm_address(value) -> str:
    return str(value or '').strip().lower()


@dataclass
class ViewerContext:
    """Everything the kind mapping needs about the active account."""
    user: object
    account: object
    account_type: str
    business_id: int | None
    owner_id: int | None = None   # the account owner's user id (not the caller's)
    owned_business_ids: set = field(default_factory=set)
    kyc_document: tuple[str, str] | None = None   # (type, number), normalized
    ramp_arrival_hashes: set = field(default_factory=set)
    destination_ids: dict = field(default_factory=dict)  # internal_id -> (type, number), normalized
    category_rules: dict = field(default_factory=dict)   # counterparty_key -> category
    category_overrides: dict = field(default_factory=dict)  # unified row id -> category


@dataclass
class Movement:
    kind: str
    direction: str
    amount: Decimal
    counterparty_key: str | None = None
    counterparty_name: str = ''
    when: datetime | None = None
    row_id: int | None = None
    category: str | None = None   # spending only; None = uncategorized


class SummaryUnavailable(Exception):
    """Evidence needed to classify a movement is invalid. The summary must
    fail visibly rather than guess (a wrong total is worse than none)."""


def _related(obj, *path):
    """Follow a chain of optional one-to-one relations. A missing record means
    "no evidence"; any other error propagates (never a silent guess)."""
    from django.core.exceptions import ObjectDoesNotExist
    for name in path:
        if obj is None:
            return None
        try:
            obj = getattr(obj, name)
        except ObjectDoesNotExist:
            return None
    return obj


def _journey(row):
    return _related(row, 'local_money_flow', 'infinia_journey')


def _payin_reason(row) -> str | None:
    """PayinAdmission.reason for an incoming local transfer, if recorded."""
    return _related(_journey(row), 'funding_credit', 'payin_admission', 'reason')


def _payin_counterparty(row) -> str | None:
    credit = _related(_journey(row), 'funding_credit')
    third = ((credit.provider_data or {}) if credit is not None else {}).get('third_party') or {}
    code, account = str(third.get('bank_code') or ''), re.sub(r'\s', '', str(third.get('account_number') or ''))
    return f'bank:{code}:{account}' if account else None


def _destination_id(row) -> str | None:
    journey = _journey(row)
    snap = (journey.destination_snapshot or {}) if journey is not None else {}
    return snap.get('destination_internal_id') or None


def _payout_counterparty(row) -> tuple[str | None, str]:
    journey = _journey(row)
    snap = (journey.destination_snapshot or {}) if journey is not None else {}
    dest = snap.get('destination_internal_id')
    return (f'dest:{dest}' if dest else None), str(snap.get('display_label') or '')


def _payout_is_own(row, ctx: ViewerContext) -> bool:
    """R2 (kept as ID match by founder decision 2026-10-04): a payout is the
    user's own account only when the destination's ID type+number exactly
    equal the verified KYC document. Missing data means "not proven" → spending."""
    if not ctx.kyc_document:
        return False
    holder = ctx.destination_ids.get(str(_destination_id(row) or ''))
    if not holder or not holder[1]:
        return False
    return holder == ctx.kyc_document


def _counterparty(row, direction: str) -> tuple[str | None, str]:
    """R5 key precedence: business > Confío user > address; the viewer's side
    is excluded so the key names the OTHER party."""
    if direction == 'sent':
        business_id, user_id = row.counterparty_business_id, row.counterparty_user_id
        address, name = row.counterparty_address or row.to_address, row.counterparty_display_name
    else:
        business_id, user_id = row.sender_business_id, row.sender_user_id
        address, name = row.sender_address or row.from_address, row.sender_display_name
    if business_id:
        return f'business:{business_id}', name or ''
    if user_id:
        return f'user:{user_id}', name or ''
    if address:
        return f'addr:{_norm_address(address)}', name or ''
    return None, name or ''


def _is_own_transfer(row, ctx: ViewerContext, direction: str) -> bool:
    """Money between the owner's personal account and a business they own.

    Ownership comes from the ACCOUNT's owner, never the caller: an employee
    viewing or labeling a business account must classify exactly as the
    owner would."""
    user_id = ctx.owner_id
    if ctx.account_type == 'business':
        other_user = row.counterparty_user_id if direction == 'sent' else row.sender_user_id
        other_biz = row.counterparty_business_id if direction == 'sent' else row.sender_business_id
        return bool(other_user == user_id and not other_biz)
    other_biz = row.counterparty_business_id if direction == 'sent' else row.sender_business_id
    return bool(other_biz and other_biz in ctx.owned_business_ids)


def classify(row, ctx: ViewerContext, require_confirmed: bool = True) -> Movement | None:
    """Kind + viewer-side USD amount for one ledger row, or None when the row
    is not a counted movement (non-USD, unconfirmed, ramp landing, …).

    require_confirmed=False classifies a still-pending payment (the success
    screen asks for a category before the ledger confirms it); totals always
    use the default."""
    from users.graphql_views import row_direction

    if row.status == 'FAILED' or (require_confirmed and row.status != 'CONFIRMED'):
        return None
    if (row.token_type or '').upper() not in USD_TOKENS:
        return None
    if (row.token_type or '').upper() == 'CUSD_PLUS' and getattr(row, 'amount_denomination', '') == 'SHARES':
        return None  # share counts are not dollars; never denominate in cUSD+ shares
    ttype = row.transaction_type
    direction = row_direction(row, ctx.user)
    if ttype == 'payroll' and ctx.account_type == 'business' and ctx.business_id:
        # A business viewing payroll: the business side decides, never the
        # (possibly owner) recipient's identity.
        if row.sender_business_id == ctx.business_id:
            direction = 'sent'
        elif row.counterparty_business_id == ctx.business_id:
            direction = 'received'
    amount = _viewer_amount(row, direction)
    if amount is None:
        return None
    kind = None

    if ttype == 'ramp':
        rt = getattr(row, 'ramp_transaction', None)
        kind = 'top_up' if rt is not None and rt.direction == 'on_ramp' else 'withdrawal'
    elif ttype == 'local_transfer':
        if direction == 'received':
            kind = 'top_up' if _payin_reason(row) == 'same_owner' else 'income_person'
        else:
            kind = 'withdrawal' if _payout_is_own(row, ctx) else 'p2p_send'
    elif ttype == 'conversion':
        conv = getattr(row, 'conversion', None)
        ctype = getattr(conv, 'conversion_type', '')
        # DELIVERED_USDT is mirrored as CONFIRMED but the user got raw USDT,
        # not savings: only a COMPLETED conversion moved money into savings.
        if ctype in ('to_savings', 'from_savings') and getattr(conv, 'status', '') == 'COMPLETED':
            kind = 'savings_in' if ctype == 'to_savings' else 'savings_out'
        else:
            kind = 'conversion'
    elif ttype == 'payment':
        kind = 'merchant' if direction == 'sent' else 'sale'
    elif ttype == 'payroll':
        kind = 'payroll_in' if direction == 'received' else 'payroll_out'
    elif ttype == 'reward':
        kind = 'bonus' if direction == 'received' else None
    elif ttype == 'presale':
        kind = 'investment_in' if direction == 'sent' else None
    elif ttype == 'humanitarian':
        kind = 'donation' if direction == 'sent' else 'income_person'
    elif ttype in ('send', 'exchange'):
        batch_kind = getattr(getattr(row, 'sponsored_batch', None), 'kind', '') or ''
        if batch_kind == 'stock_buy':
            kind = 'investment_in'
        elif batch_kind == 'stock_sell':
            kind = 'investment_out'
        elif direction == 'received' and _norm_address(row.transaction_hash) in ctx.ramp_arrival_hashes:
            return None  # the USDT landing of an on-ramp already counted as top_up
        elif _is_own_transfer(row, ctx, direction):
            kind = 'own_transfer'
        elif direction == 'sent':
            kind = 'merchant' if row.counterparty_business_id else 'p2p_send'
        elif direction == 'received':
            kind = 'income_person'  # incl. unknown external wallets (R6, D9)
    if kind is None or direction not in ('sent', 'received', 'conversion'):
        return None

    key, name = (None, '')
    if kind in COUNTERPARTY_KINDS:
        if ttype == 'local_transfer' and direction == 'received':
            key, name = _payin_counterparty(row), row.sender_display_name or ''
        elif ttype == 'local_transfer':
            key, name = _payout_counterparty(row)
        else:
            key, name = _counterparty(row, direction)
    # Cents once, here: every total, group and list then adds the same
    # numbers, so a drill-down always sums to the figure it was opened from.
    movement = Movement(kind=kind, direction=direction, amount=amount.quantize(CENT, rounding=ROUND_HALF_UP),
                        counterparty_key=key, counterparty_name=name,
                        when=row.transaction_date, row_id=getattr(row, 'pk', None))
    movement.category = category_for(movement, ctx)
    return movement


def category_for(movement: Movement, ctx: ViewerContext) -> str | None:
    """Read-time category (R20): this row's override > its counterparty's
    rule > uncategorized. Only spending movements carry a category."""
    if movement.kind not in SPENDING_KINDS:
        return None
    if movement.row_id is not None and movement.row_id in ctx.category_overrides:
        return ctx.category_overrides[movement.row_id]
    if movement.counterparty_key:
        return ctx.category_rules.get(movement.counterparty_key)
    return None


@dataclass
class Totals:
    income: Decimal = Decimal('0')
    spending: Decimal = Decimal('0')
    top_ups: Decimal = Decimal('0')
    withdrawals: Decimal = Decimal('0')
    savings_net: Decimal = Decimal('0')      # + = moved into savings
    investment_net: Decimal = Decimal('0')   # + = bought
    movement_count: int = 0                  # Entró + Salió movements only
    spending_by_category: dict = field(default_factory=dict)  # category | 'uncategorized' -> Decimal

    def add(self, m: Movement) -> None:
        if m.kind in INCOME_KINDS:
            self.income += m.amount
            self.movement_count += 1
        elif m.kind in SPENDING_KINDS:
            self.spending += m.amount
            self.movement_count += 1
            bucket = m.category or 'uncategorized'
            self.spending_by_category[bucket] = self.spending_by_category.get(bucket, Decimal('0')) + m.amount
        elif m.kind == 'top_up':
            self.top_ups += m.amount
        elif m.kind == 'withdrawal':
            self.withdrawals += m.amount
        elif m.kind == 'savings_in':
            self.savings_net += m.amount
        elif m.kind == 'savings_out':
            self.savings_net -= m.amount
        elif m.kind == 'investment_in':
            self.investment_net += m.amount
        elif m.kind == 'investment_out':
            self.investment_net -= m.amount


@dataclass
class CounterpartyTotal:
    key: str
    name: str
    received: Decimal = Decimal('0')
    sent: Decimal = Decimal('0')


@dataclass
class MonthSummary:
    year: int
    month: int
    current: Totals
    previous: Totals
    previous_is_partial: bool
    counterparties: list


def build_context(user, account, account_type, business_id) -> ViewerContext:
    from users.models import Account
    owner_id = getattr(account, 'user_id', None) or getattr(user, 'id', None)
    owned = set(Account.objects.filter(
        user_id=owner_id, account_type='business', deleted_at__isnull=True,
        business_id__isnull=False).values_list('business_id', flat=True))
    from payment_accounts.models import ProviderProfile
    kyc = None
    profile = ProviderProfile.objects.filter(confio_account=account).exclude(
        identity_snapshot={}).order_by('-id').first()
    snap = getattr(profile, 'identity_snapshot', None) or {}
    number = _norm_id(snap.get('document_number'))
    if number:
        kyc = (_doc_family(snap.get('document_type')), number)
    return ViewerContext(user=user, account=account, account_type=account_type,
                         business_id=business_id, owner_id=owner_id, owned_business_ids=owned,
                         kyc_document=kyc)


def _ramp_arrival_hashes(scope) -> set:
    """USDT landing hashes of ALL the account's on-ramps — not just the
    reporting window, because a landing can trail its ramp by up to two
    weeks, and the same landing must be excluded from every window alike."""
    hashes = set()
    for metadata in scope.filter(transaction_type='ramp', ramp_transaction__direction='on_ramp') \
            .values_list('ramp_transaction__metadata', flat=True):
        h = (metadata or {}).get('bsc_arrival_tx_hash')
        if h:
            hashes.add(_norm_address(h))
    return hashes


ROW_RELATIONS = ('ramp_transaction', 'conversion', 'sponsored_batch',
                 'sender_user', 'counterparty_user', 'sender_business', 'counterparty_business',
                 'local_money_flow__infinia_journey__funding_credit__payin_admission')


def prepare_context(user, account, account_type, business_id, scope, rows) -> ViewerContext:
    """Everything classify() needs for these rows, loaded in bulk."""
    from users.models_cashflow import CounterpartyRule, MovementOverride
    ctx = build_context(user, account, account_type, business_id)
    ctx.ramp_arrival_hashes = _ramp_arrival_hashes(scope)
    dest_ids = {d for d in (_destination_id(r) for r in rows if r.transaction_type == 'local_transfer') if d}
    if dest_ids:
        from payment_accounts.models import PayoutDestination
        ctx.destination_ids = {
            str(internal_id): (_doc_family(id_type), _norm_id(id_number))
            for internal_id, id_type, id_number in PayoutDestination.objects.filter(
                internal_id__in=dest_ids).values_list('internal_id', 'holder_id_type', 'holder_id_number')
        }
    ctx.category_rules = dict(CounterpartyRule.objects.filter(account=account).values_list('counterparty_key', 'category'))
    ctx.category_overrides = dict(MovementOverride.objects.filter(
        account=account, movement_id__in=[r.pk for r in rows]).values_list('movement_id', 'category'))
    return ctx


def _stamp_viewer(row, account, account_type, business_id):
    from users.graphql_views import _viewer_address_for
    row._user_address = _viewer_address_for(row, account)
    row._account_type = account_type
    row._account_business_id = business_id if account_type == 'business' else None


def resolve_movement(user, account, account_type, business_id, movement_id=None, internal_id=None):
    """(row, movement) for one ledger row INSIDE the active account's scope,
    found by unified id or by the send/payment internal_id the success screens
    hold; (None, None) when it isn't this account's or isn't a movement."""
    from django.db.models import Q
    from users.graphql_views import account_unified_queryset
    scope = account_unified_queryset(user, account, account_type, business_id)
    if movement_id:
        lookup = Q(pk=movement_id)
    elif internal_id:
        lookup = Q(send_transaction__internal_id=internal_id) | Q(payment_transaction__internal_id=internal_id)
    else:
        return None, None
    row = scope.filter(lookup).select_related(*ROW_RELATIONS).first()
    if row is None:
        return None, None
    _stamp_viewer(row, account, account_type, business_id)
    ctx = prepare_context(user, account, account_type, business_id, scope, [row])
    return row, classify(row, ctx, require_confirmed=False)


def summarize(user, account, account_type, business_id, year, month, tz, now=None) -> MonthSummary:
    from django.utils import timezone as dj_tz
    from users.graphql_views import account_unified_queryset

    now = now or dj_tz.now()
    start, end = month_window(year, month, tz)
    p_start, p_end, partial = comparison_window(year, month, now, tz)
    scope = account_unified_queryset(user, account, account_type, business_id)
    rows = list(scope.filter(transaction_date__gte=p_start, transaction_date__lt=end).select_related(*ROW_RELATIONS))
    ctx = prepare_context(user, account, account_type, business_id, scope, rows)

    current, previous = Totals(), Totals()
    people: dict[str, CounterpartyTotal] = {}
    for row in rows:
        when = row.transaction_date
        in_current = start <= when < end
        in_previous = p_start <= when < p_end
        if not (in_current or in_previous):
            continue
        _stamp_viewer(row, account, account_type, business_id)
        movement = classify(row, ctx)
        if movement is None:
            continue
        if in_current:
            current.add(movement)
            if movement.kind in COUNTERPARTY_KINDS and movement.counterparty_key:
                entry = people.setdefault(movement.counterparty_key, CounterpartyTotal(
                    key=movement.counterparty_key, name=movement.counterparty_name))
                if movement.kind in INCOME_KINDS:
                    entry.received += movement.amount
                else:
                    entry.sent += movement.amount
                if not entry.name and movement.counterparty_name:
                    entry.name = movement.counterparty_name
        if in_previous:
            previous.add(movement)

    top = sorted(people.values(), key=lambda c: c.received + c.sent, reverse=True)[:5]
    return MonthSummary(year=year, month=month, current=current, previous=previous,
                        previous_is_partial=partial, counterparties=top)


OWN_MONEY_KINDS = {'top_up', 'withdrawal', 'savings_in', 'savings_out', 'investment_in', 'investment_out'}
MOVEMENT_FILTERS = {'income', 'spending', 'category', 'uncategorized', 'counterparty', 'counterparties',
                    'own_money'}
# "Entre tus cuentas" rows: each opens only the movements behind its own line
# (savings/investment are nets, so both directions are listed).
OWN_MONEY_BUCKETS = {
    'top_up': {'top_up'},
    'withdrawal': {'withdrawal'},
    'savings': {'savings_in', 'savings_out'},
    'investment': {'investment_in', 'investment_out'},
}


def month_movements(user, account, account_type, business_id, year, month, tz,
                    filter_by: str, value: str | None = None) -> list:
    """The movements behind one number on the month screen, newest first.

    Same rows and the same classify() as summarize(), so a list always adds
    up to the total it was opened from (Salió, a category, "Sin categoría",
    a person in "Con quién", or "Entre tus cuentas")."""
    from users.graphql_views import account_unified_queryset
    if filter_by not in MOVEMENT_FILTERS:
        return []
    start, end = month_window(year, month, tz)
    scope = account_unified_queryset(user, account, account_type, business_id)
    rows = list(scope.filter(transaction_date__gte=start, transaction_date__lt=end).select_related(*ROW_RELATIONS))
    ctx = prepare_context(user, account, account_type, business_id, scope, rows)
    out = []
    for row in rows:
        _stamp_viewer(row, account, account_type, business_id)
        m = classify(row, ctx)
        if m is None:
            continue
        keep = (
            (filter_by == 'income' and m.kind in INCOME_KINDS)
            or (filter_by == 'spending' and m.kind in SPENDING_KINDS)
            or (filter_by == 'category' and m.kind in SPENDING_KINDS and m.category == value)
            or (filter_by == 'uncategorized' and m.kind in SPENDING_KINDS and m.category is None)
            or (filter_by == 'counterparty' and m.kind in COUNTERPARTY_KINDS and m.counterparty_key == value)
            or (filter_by == 'counterparties' and m.kind in COUNTERPARTY_KINDS and m.counterparty_key)
            or (filter_by == 'own_money' and m.kind in OWN_MONEY_BUCKETS.get(value, OWN_MONEY_KINDS if value is None else ()))
        )
        if keep:
            out.append(m)
    out.sort(key=lambda m: m.when, reverse=True)
    return out
