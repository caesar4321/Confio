"""The Cuenta inteligente offer: prices, who may subscribe, the copy the
sign-up screen shows (spec 7.3, 8.3). Prices come from the factory; the
settings values are a display fallback only."""
from __future__ import annotations

import logging
import re
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from . import abi, chain

logger = logging.getLogger(__name__)

PLANS = ('annual', 'monthly')
PRICE_SETTINGS = {'monthly': 'SMART_ACCOUNT_MONTHLY_PRICE_USD', 'annual': 'SMART_ACCOUNT_ANNUAL_PRICE_USD'}
PRICE_FALLBACK = {'monthly': '14.99', 'annual': '149.99'}
WINDOW_OPTIONS_DAYS = [90, 180, 365]
DEFAULT_WINDOW_DAYS = 180

DISCLOSURES = [
    'El precio es el del plan que elijas, por 30 días (mensual) o 365 días (anual). Se renueva al precio vigente '
    'en la fecha de renovación, se cobra desde adentro de tu Cuenta inteligente y no hay reembolsos.',
    'El cobro usa primero tu Confío Dollar, luego tu Confío Dollar+. Si no alcanza, después de varios avisos se '
    'vende parte de tus inversiones, solo por el valor de un período.',
    'Solo lo que está dentro de la Cuenta inteligente se automatiza y queda cubierto por tu beneficiario. '
    'Tu cuenta personal no.',
    'La comisión de conversión de 0.9% se aplica igual que en el resto de Confío. No hay descuento.',
    'Si cancelas, al terminar el período pagado todo vuelve a tu cuenta personal y termina la cobertura de tu '
    'beneficiario.',
    'Es una cuenta de autocustodia, no una cuenta bancaria.',
]
BENEFICIARY_DISCLOSURE = (
    'Si tu beneficiario inicia un reclamo y tú no firmas ninguna acción en la cuenta durante todo el plazo '
    '(Confío agrega una automáticamente a cada operación que firmas desde tu cuenta personal), tu beneficiario '
    'pasa a ser dueño de la cuenta y de todo lo que hay en ella. Si no ves ningún aviso durante todo el plazo, '
    'pierdes la cuenta.'
)

# The same disclosure as short sentences for the setup screen; the app fills
# {name} (the beneficiary) and {days} (the chosen window).
BENEFICIARY_RISK_DISCLOSURE = [
    'Si {name} inicia un reclamo, tienes {days} días para cancelarlo.',
    'Cualquier acción que firmes en tu Cuenta inteligente lo cancela. Confío agrega una automáticamente a cada '
    'operación que firmas desde tu cuenta personal.',
    'Si no firmas nada durante los {days} días, {name} pasa a ser dueño de la cuenta y de todo lo que hay en ella.',
    'Si no ves ningún aviso durante todo ese plazo, pierdes la cuenta.',
]

BENEFITS = {
    'beneficiary': ('Beneficiario', 'Nombra a una persona que recibe la cuenta si dejas de usarla.'),
    'payments': ('Pagos y envíos automáticos', 'Programa envíos y pagos diarios, semanales, quincenales o mensuales.'),
    'investing': ('Inversión automática', 'Compra acciones, bitcoin y oro de forma periódica.'),
    'assistant': ('Confío IA+', 'Pídele por chat que compre por ti en tiendas en línea, o que cree y cambie tus '
                                'pagos e inversiones automáticas. Tú eliges y confirmas.'),
}
# Once the account itself pays (the purchase spender and the v2 implementation are live), what the chat does
# without a signature each time (docs/designs/hands-off-account.md). Never said before it is true.
ASSISTANT_HANDS_OFF = ('Pídele por chat que compre en tiendas en línea y en Comprar, o que invierta en acciones{crypto}, '
                       'sin firmar cada vez, dentro del límite semanal que eliges. También crea y cambia tus pagos e '
                       'inversiones automáticas.')


def hands_off_live() -> bool:
    """The account pays purchases and trades by itself: the spender and the v2 implementation are configured."""
    try:
        from . import hands_off, purchases
        return bool(hands_off.enabled() and purchases.spender_address())
    except Exception:  # noqa: BLE001 — an unread switch says only what is true today
        return False


def benefit(key: str, *, crypto: bool = True) -> tuple[str, str]:
    """(title, body) of one benefit line, as true for this build today."""
    title, body = BENEFITS[key]
    if key == 'assistant' and hands_off_live():
        body = ASSISTANT_HANDS_OFF.format(crypto=', oro y bitcoin' if crypto else '')
    return title, body
HEADLINE_ORDER = {
    'beneficiary_first': ['beneficiary', 'payments', 'investing', 'assistant'],
    'automation_first': ['payments', 'investing', 'beneficiary', 'assistant'],
}


def _valid_price(value) -> str | None:
    value = str(value or '').strip()
    return value if re.fullmatch(r'[0-9]{1,4}(\.[0-9]{2})?', value) else None


def settings_price(plan: str) -> str:
    return _valid_price(getattr(settings, PRICE_SETTINGS[plan], '')) or PRICE_FALLBACK[plan]


def default_plan() -> str:
    value = str(getattr(settings, 'SMART_ACCOUNT_DEFAULT_PLAN', 'annual') or 'annual').strip().lower()
    return value if value in PLANS else 'annual'


def _usd_text(wei: int) -> str:
    return format((Decimal(int(wei)) / Decimal(10 ** 18)).quantize(Decimal('0.01')), 'f')


def factory_prices(*, fresh: bool = False) -> dict | None:
    """{plan: {'price_wei', 'next_wei', 'next_at'}} from the factory, or None
    when it is not configured or unreadable (display then falls back)."""
    if not chain.factory_address():
        return None
    key = 'smart_account_factory_prices_v1'
    cached = None if fresh else cache.get(key)
    if cached is not None:
        return cached
    try:
        out = {}
        for plan in PLANS:
            price = chain.factory_fee_usd_wei(plan)
            next_wei, next_at = chain.factory_scheduled_fee(plan)
            if price <= 0:
                raise chain.ChainError('factory fee is zero')
            out[plan] = {'price_wei': price, 'next_wei': next_wei, 'next_at': next_at}
    except Exception:  # noqa: BLE001 — display only; signing re-reads fresh and fails closed
        logger.warning('smart account: factory prices unreadable', exc_info=True)
        return None
    cache.set(key, out, 60)
    return out


def signing_fee_wei(plan: str) -> int:
    """The fee a subscribe will be signed against (maxFeeUsd). Read fresh
    from the factory; raises when unreadable. Never the settings value."""
    return chain.factory_fee_usd_wei(plan)


def plans() -> list[dict]:
    prices = factory_prices()
    out = []
    for plan in PLANS:
        row = (prices or {}).get(plan)
        entry = {
            'key': plan,
            'price_usd': _usd_text(row['price_wei']) if row else settings_price(plan),
            'period_days': abi.PERIOD_DAYS[plan],
            'next_price_usd': None,
            'next_price_effective_at': None,
            'is_default': plan == default_plan(),
        }
        if row and row['next_wei'] and row['next_at']:
            entry['next_price_usd'] = _usd_text(row['next_wei'])
            entry['next_price_effective_at'] = chain.to_dt(row['next_at'])
        out.append(entry)
    return out


def price_usd(plan: str) -> str:
    return next(p['price_usd'] for p in plans() if p['key'] == plan)


def _id_list(setting: str) -> set:
    raw = str(getattr(settings, setting, '') or '')
    return {p.strip() for p in raw.split(',') if p.strip()}


def canary_allows(user_id) -> bool:
    """SMART_ACCOUNT_ALLOWED_USER_IDS: ids, or '*' for everyone. Empty means
    nobody (fail closed)."""
    allowed = _id_list('SMART_ACCOUNT_ALLOWED_USER_IDS')
    return '*' in allowed or (user_id is not None and str(user_id) in allowed)


def beneficiary_enabled(user_id) -> bool:
    if not chain.enabled():
        return False
    if bool(getattr(settings, 'SMART_ACCOUNT_BENEFICIARY_ENABLED', False)):
        return True
    return user_id is not None and str(user_id) in _id_list('SMART_ACCOUNT_BENEFICIARY_ALLOWED_USER_IDS')


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', value):
        return None
    return tuple(int(part) for part in value.split('.'))


def build_supported(meta) -> bool:
    floor = _version(str(getattr(settings, 'SMART_ACCOUNT_MIN_APP_VERSION', '') or ''))
    version = _version(str((meta or {}).get('HTTP_X_CONFIO_VERSION', '') or ''))
    return floor is not None and version is not None and version >= floor


def payout_rails() -> list[str]:
    """Rails confirmed for unattended payouts. Empty = payment rules are
    neither offered nor run."""
    from payment_accounts import local_money
    from . import payouts
    rails = [r.strip() for r in str(getattr(settings, 'SMART_ACCOUNT_PAYOUT_RAILS', '') or '').split(',')]
    out = []
    for r in rails:
        if not r or r in out:
            continue
        # The unattended provider path of the rail's adapter must be verified
        # (payouts.rail_ready): Infinia's flag for local_money rails,
        # SMART_ACCOUNT_PAYOUT_VERIFIED_ADAPTERS for the others.
        if not payouts.rail_ready(r):
            continue
        if r == payouts.VE_PAGOMOVIL:
            out.append(r)
            continue
        # A QR is a one-off payment, never a saved recurring destination.
        if (r in local_money.METHODS and local_money.METHODS[r].direction == 'send'
                and not r.endswith('_qr') and local_money.METHODS[r].kind != 'qr'):
            out.append(r)
    return out


def payout_rail_options() -> list[dict]:
    """{key, label, hint} for exactly the rails payout_rails() offers, named
    as the rest of Confío names them (local_money.METHODS; Pago Móvil as the
    VE screens name it). A rail turned on by the server switch is named by
    the server: no app release."""
    from payment_accounts import local_money
    from . import payouts
    out = []
    for r in payout_rails():
        if r == payouts.VE_PAGOMOVIL:
            out.append({'key': r, 'label': payouts.VE_PAGOMOVIL_LABEL, 'hint': payouts.VE_PAGOMOVIL_HINT})
        else:
            out.append({'key': r, 'label': local_money.METHODS[r].title,
                        'hint': local_money.METHODS[r].subtitle or None})
    return out


def rail_names() -> list[str]:
    """The offered rails' names for Spanish copy ("Pix", "CLABE")."""
    return [o['label'] for o in payout_rail_options()]


def join_es(names: list[str], word: str = 'y') -> str:
    """'A', 'A y B', 'A, B y C'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return ''.join(names)
    return ', '.join(names[:-1]) + f' {word} ' + names[-1]


BLOCKED = {
    # Flag off / not on the canary list: the real pitch is shown to everyone on
    # a supported build (founder, 2026-11-21); only signing waits.
    'disabled': 'Todavía no puedes abrir tu Cuenta inteligente.',
    'canary': 'Todavía no puedes abrir tu Cuenta inteligente.',
    'build': 'Actualiza Confío para abrir tu Cuenta inteligente.',
    'personal_only': 'La Cuenta inteligente solo está disponible para cuentas personales.',
    'identity': 'Verifica tu identidad para abrir tu Cuenta inteligente.',
    'identity_hold': 'Tu cuenta está en revisión. Escríbenos por soporte para continuar.',
    'minor': 'La Cuenta inteligente está disponible para mayores de 18 años.',
    'chain_unavailable': 'No pudimos consultar la red. Inténtalo de nuevo en unos minutos.',
    'opening': 'Tu Cuenta inteligente se está abriendo. Espera unos minutos.',
}


OPENING_WINDOW_MINUTES = 30


def subscribe_in_flight(user, own) -> bool:
    """True while this person's subscribe batch went out (signed, sent or
    mined) but the account row does not show it yet: reconciliation is
    asynchronous. The account then reads 'opening' and no second subscribe
    is offered or prepared. Bounded: after the window the row speaks; a
    reverted batch drops out at once."""
    if user is None or (own is not None and own.status in ('active', 'cancel_pending')):
        return False
    from datetime import timedelta

    from django.utils import timezone

    from .models import SmartAccountPreparedAction
    since = timezone.now() - timedelta(minutes=OPENING_WINDOW_MINUTES)
    return SmartAccountPreparedAction.objects.filter(
        user=user, kind='smart_subscribe', consumed=True, consumed_at__gte=since,
        sponsored_batch__status__in=('signed', 'sent', 'confirmed')).exists()


def subscribe_block(user, *, personal_context: bool, meta) -> str | None:
    """Reason code this person cannot subscribe, or None. Flag, canary list,
    build floor, personal non-employee context, identity rules."""
    if not chain.enabled():
        return 'disabled'
    if not personal_context:
        return 'personal_only'
    if not canary_allows(getattr(user, 'pk', None)):
        return 'canary'
    if not build_supported(meta):
        return 'build'
    from security.identity_status import is_identity_verified
    if not is_identity_verified(user):
        return 'identity'
    from security.minors import is_known_minor
    if is_known_minor(user):
        return 'minor'
    from security.identity_reuse import outgoing_identity_restriction
    if outgoing_identity_restriction(user):
        return 'identity_hold'
    return wallet_chain_block(user)


def wallet_chain_block(user) -> str | None:
    """'chain_unavailable' when the factory cannot tell whether this person's
    wallet can subscribe; None otherwise. With no own row, the factory may
    already map the signer to a clone: one still theirs (created, not
    reconciled) is subscribed in place; one inherited or owned by someone
    else is replaced by a new account at the next generation (decision 33,
    spec 4.3). Either way the person may subscribe, but only on a readable
    chain: unknown is never 'may subscribe'."""
    from . import context
    from .models import SmartAccount
    if context.own_account(user) is not None:
        return None
    personal = context.personal_account(user)
    signer = (getattr(personal, 'bsc_address', '') or '').lower()
    if not signer:
        return None
    try:
        existing = chain.account_of(signer)
        mapped = int(existing, 16) != 0
    except Exception:  # noqa: BLE001 — unknown is never 'may subscribe'
        logger.warning('smart account: accountOf read failed for subscribe check', exc_info=True)
        return 'chain_unavailable'
    if not mapped:
        return None
    # Fast path: inheritance is irreversible, so a mirror that already shows
    # it can never disagree with the chain: a re-open.
    if SmartAccount.objects.filter(contract_address__iexact=existing, status='inherited').exists():
        return None
    return 'chain_unavailable' if mapped_clone_state(user, existing, signer) == 'chain_unavailable' else None


def mapped_clone_state(user, clone: str, signer: str) -> str:
    """Chain truth for the clone factory.accountOf(signer) names (spec 6.5):
    'own' when the signer still owns it and it is not inherited (created,
    not reconciled: subscribe in place); 'replaceable' when it is inherited()
    or its owner() is not the signer, whatever the mirror says (a
    ClaimExecuted it has not applied): the next createAccount opens a new
    account (decision 33). 'chain_unavailable' when unreadable: fail closed."""
    from .models import SmartAccount
    try:
        state = chain.account_control(clone)
        owner = str(state['owner'] or '').lower()
        if not int(owner or '0x0', 16):
            raise chain.ChainError(f'{clone} has no owner')
    except Exception:  # noqa: BLE001 — unknown is never 'may subscribe'
        logger.warning('smart account: owner()/inherited() read failed for subscribe check', exc_info=True)
        return 'chain_unavailable'
    if state['inherited'] or owner != (signer or '').lower():
        return 'replaceable'
    if SmartAccount.objects.filter(contract_address__iexact=clone).exclude(owner_user=user).exists():
        # The chain says this signer owns it, the mirror names someone else.
        logger.warning('smart account %s: mirror owner differs from chain owner %s', clone, owner)
        try:
            from config.ops_alerts import send_ops_alert
            send_ops_alert(f'Cuenta inteligente {clone}: el espejo nombra otro dueño que la red ({owner}). '
                           f'Revisión manual.', dedupe_key=f'smart_owner_mirror_differs_{clone}',
                           dedupe_seconds=86400)
        except Exception:  # noqa: BLE001
            logger.exception('smart account ops alert failed for %s', clone)
    return 'own'


def viewer_dollar(user, meta=None) -> str:
    """'cusd_plus' for an Ondo-eligible viewer, else 'cusd' (decision 17).
    With a request, the full mint policy (phone AND IP); without, phone."""
    from cusd_plus.eligibility import check_savings_mint_eligibility, is_ondo_eligible
    eligible = check_savings_mint_eligibility(user, meta) if meta is not None else is_ondo_eligible(user)
    return 'cusd_plus' if eligible else 'cusd'


def crypto_investing_enabled(user, meta) -> bool:
    from cusd_plus import crypto_risk
    try:
        return bool(crypto_risk.surfaces_enabled(user, meta or {}))
    except Exception:  # noqa: BLE001 — a hidden surface, never an error
        logger.warning('smart account: crypto surface check failed', exc_info=True)
        return False
