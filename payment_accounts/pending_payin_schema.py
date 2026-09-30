"""GraphQL for pay-ins held until Confío Face (docs/plans/infinia-payin-face-hold.md).

The account always comes from the JWT context. Only a personal account has
held pay-ins; business accounts get an empty list.
"""
import logging

import graphene

logger = logging.getLogger(__name__)


class PendingIncomingPayinType(graphene.ObjectType):
    id = graphene.ID(required=True)
    state = graphene.String(required=True)
    amount = graphene.String(required=True)
    asset = graphene.String(required=True)
    country = graphene.String(required=True)
    payer_name = graphene.String()
    received_at = graphene.DateTime(required=True)
    returns_at = graphene.DateTime(required=True)
    return_amount = graphene.String()
    return_deduction = graphene.String()
    journey_id = graphene.ID()


def _personal_account(info):
    from .schema import _active_account
    user = getattr(info.context, 'user', None)
    if not (user and user.is_authenticated):
        return None
    account = _active_account(info)
    return account if account.account_type == 'personal' else None


class PendingPayinQuery(graphene.ObjectType):
    pending_incoming_payins = graphene.List(graphene.NonNull(PendingIncomingPayinType), required=True)

    def resolve_pending_incoming_payins(self, info):
        from .payin_hold import serialize, visible_for
        try:
            account = _personal_account(info)
        except Exception:
            return []
        if account is None:
            return []
        return [PendingIncomingPayinType(**serialize(row)) for row in visible_for(account)]


class ReleasePendingPayins(graphene.Mutation):
    """Receive every held pay-in. Needs a Confío Face check passed within the
    last few minutes; otherwise answers nextStep 'face_check'."""

    success = graphene.Boolean(required=True)
    error = graphene.String()
    next_step = graphene.String()
    released = graphene.List(graphene.NonNull(PendingIncomingPayinType), required=True)

    def mutate(self, info):
        from security.face_step_up import FACE_STEP_UP_MESSAGE, FACE_STEP_UP_NEXT_STEP, step_up_enabled
        from .payin_hold import needs_face, release_for, serialize
        try:
            account = _personal_account(info)
        except Exception:
            account = None
        if account is None:
            return ReleasePendingPayins(success=False, error='Cuenta no disponible.', released=[])
        if step_up_enabled() and needs_face(account):
            return ReleasePendingPayins(success=False, error=FACE_STEP_UP_MESSAGE,
                                        next_step=FACE_STEP_UP_NEXT_STEP, released=[])
        try:
            rows = release_for(account)
        except Exception:
            logger.exception('Releasing held pay-ins failed for account %s', account.pk)
            return ReleasePendingPayins(success=False, error='No pudimos recibir tu dinero. Intenta de nuevo.',
                                        released=[])
        return ReleasePendingPayins(success=True, released=[PendingIncomingPayinType(**serialize(r)) for r in rows])


class PendingPayinMutation(graphene.ObjectType):
    release_pending_payins = ReleasePendingPayins.Field()
