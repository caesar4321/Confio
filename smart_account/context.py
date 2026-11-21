"""JWT account context for Cuenta inteligente (spec 7.2).

Account context comes from the JWT only. A `smart` context has no key of its
own: the signer is always the user's personal account (index 0).

Dual enforcement of "a smart context reaches only what the account supports":
1. users.jwt_context.get_jwt_business_context_with_validation returns None
   for a smart context unless the caller opts in (allow_smart=True);
2. SmartContextGateMiddleware refuses every mutation outside an explicit
   allowlist while the request's JWT is a smart context, which also covers
   mutations that never read the account context at all.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from graphql import GraphQLError

logger = logging.getLogger(__name__)

SMART = 'smart'
REFUSAL_CODE = 'smart_context_not_supported'
REFUSAL_MESSAGE = 'Esta función no está disponible desde tu Cuenta inteligente. Cambia a tu cuenta personal.'


class ContextError(Exception):
    def __init__(self, code: str, message: str = ''):
        self.code = code
        self.message = message or MESSAGES.get(code, MESSAGES['context_not_allowed'])
        super().__init__(code)


MESSAGES = {
    'auth_required': 'Inicia sesión para continuar.',
    'context_not_allowed': 'No pudimos validar tu cuenta. Vuelve a intentarlo.',
    'personal_only': 'La Cuenta inteligente solo está disponible para cuentas personales.',
    'no_wallet': 'Tu cuenta personal todavía no tiene una billetera activa.',
}


@dataclass
class Viewer:
    user: object
    personal_account: object       # users.Account personal_0: the signer
    context_type: str              # 'personal' | 'smart'
    smart_index: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def signer_address(self) -> str:
        return (self.personal_account.bsc_address or '').lower()


def owned_smart_account(user, account_index: int = 0):
    """The SmartAccount behind the user's `smart` account row at this index
    (0 = own, 1+ = inherited), or None."""
    from .models import SmartAccount
    return (SmartAccount.objects
            .filter(owner_user=user, account__user=user, account__account_type=SMART,
                    account__account_index=int(account_index), account__deleted_at__isnull=True)
            .select_related('account', 'owner_account').first())


def own_account(user):
    """The user's own (non-inherited) account row, or None."""
    from .models import SmartAccount
    return (SmartAccount.objects.filter(owner_user=user).exclude(status='inherited')
            .select_related('account', 'owner_account').first())


def personal_account(user):
    from users.models import Account
    return Account.objects.filter(
        user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()


def resolve_viewer(info, *, require_wallet: bool = True) -> Viewer:
    """The JWT viewer for a Cuenta inteligente resolver. Refuses business
    and employee contexts; never reads an account id or address from the
    client."""
    from users.jwt_context import get_jwt_business_context_with_validation

    user = getattr(info.context, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        raise ContextError('auth_required')
    ctx = get_jwt_business_context_with_validation(info, required_permission=None, allow_smart=True)
    if not ctx:
        raise ContextError('context_not_allowed')
    account_type = ctx.get('account_type')
    if account_type not in ('personal', SMART) or ctx.get('business_id'):
        raise ContextError('personal_only')
    try:
        index = int(ctx.get('account_index') or 0)
    except (TypeError, ValueError) as exc:
        raise ContextError('context_not_allowed') from exc
    if account_type == 'personal' and index != 0:
        raise ContextError('personal_only')
    personal = personal_account(user)
    if personal is None or (require_wallet and not personal.bsc_address):
        raise ContextError('no_wallet')
    return Viewer(user=user, personal_account=personal, context_type=account_type,
                  smart_index=index if account_type == SMART else 0,
                  meta=dict(getattr(info.context, 'META', {}) or {}))


def resolve_owner_any_context(info) -> Viewer:
    """For the two things an owner must reach from EVERY context (personal,
    business owner, employee, smart): cancelling a claim on their own
    account, and the claim alert. Identity is the JWT user alone; the signer
    is their personal account. Nothing here reads the active account."""
    user = getattr(info.context, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        raise ContextError('auth_required')
    personal = personal_account(user)
    if personal is None or not personal.bsc_address:
        raise ContextError('no_wallet')
    return Viewer(user=user, personal_account=personal, context_type='personal',
                  meta=dict(getattr(info.context, 'META', {}) or {}))


def jwt_account_type(context) -> str | None:
    """account_type claim of the request's JWT (None when there is none).
    Cached on the request. Signature and token version are verified by the
    JWT middleware; this only reads the claim."""
    cached = getattr(context, '_smart_ctx_account_type', False)
    if cached is not False:
        return cached
    value = None
    try:
        header = (getattr(context, 'META', {}) or {}).get('HTTP_AUTHORIZATION', '') or ''
        if header.startswith('JWT '):
            from graphql_jwt.utils import jwt_decode
            value = jwt_decode(header[4:]).get('account_type', 'personal')
    except Exception:  # noqa: BLE001 — an unreadable token is not a smart context
        value = None
    try:
        context._smart_ctx_account_type = value
    except Exception:  # noqa: BLE001
        pass
    return value


def is_smart_request(request) -> bool:
    """For REST views and websocket consumers that read the JWT themselves."""
    return jwt_account_type(request) == SMART


# Mutations a smart-context token may call. Everything else is refused.
ALLOWED_MUTATIONS = frozenset({
    # session
    'refreshToken', 'switchAccountToken', 'invalidateAuthTokens',
    'registerFcmToken', 'unregisterFcmToken', 'markNotificationRead', 'markAllNotificationsRead',
    'trackFunnelEvent',
    # Confío Face (security/schema.py): a send rule and a beneficiary
    # designation claim a Face check at prepare. Both act only on the JWT
    # user's own FaceCheck rows and move no money; the status read
    # (faceStepUpStatus) is a query and not gated here.
    'startFaceCheck', 'completeFaceCheck',
    # the relay (accepts only batches prepared below while in this context)
    'sponsorBscBatch',
    # Cuenta inteligente
    'prepareSmartAccountSubscribe', 'prepareSmartAccountDeposit', 'prepareSmartAccountMoveEverything',
    'prepareSmartAccountWithdraw', 'prepareSmartAccountPlanChange', 'prepareSmartAccountCancel',
    'prepareSmartAccountUndoCancel', 'prepareSmartAccountSendRule', 'prepareSmartAccountPayoutRule',
    'prepareSmartAccountBuyRule', 'prepareSmartAccountCancelRule', 'prepareSmartAccountTrade',
    'prepareBeneficiaryDesignation', 'prepareBeneficiaryDesignationWithdrawal', 'prepareBeneficiaryRemoval',
    'prepareClaimCancel', 'prepareBeneficiaryAcceptance', 'declineBeneficiaryDesignation',
    'prepareBeneficiaryClaim', 'prepareBeneficiaryClaimExecute', 'prepareInheritedWithdraw',
    'prepareBeneficiaryWindowChange',
})


class SmartContextGateMiddleware:
    """Graphene middleware: with a smart-context JWT, only ALLOWED_MUTATIONS
    (and no subscription) may run. Queries are left to the per-resolver
    context helpers, which refuse a smart context by default."""

    def resolve(self, next, root, info, **args):
        if info.path.prev is None and info.operation.operation.value in ('mutation', 'subscription'):
            if jwt_account_type(info.context) == SMART:
                if (info.operation.operation.value == 'subscription'
                        or info.field_name not in ALLOWED_MUTATIONS):
                    logger.info('smart context refused %s', info.field_name)
                    raise GraphQLError(REFUSAL_MESSAGE, extensions={'code': REFUSAL_CODE})
        return next(root, info, **args)
