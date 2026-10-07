"""GraphQL for the local rail waitlist ("Próximamente" rows on Enviar/Recibir).

Write-only from the client: joining is all the app does. How many people
wait for each rail is analytics for us (admin), never shown in the app.

The waitlist is per PERSON, not per account — a business and its owner are
one person waiting for the same rail — so it keys on the authenticated user
and takes no account parameter at all.
"""
import logging

import graphene

from users.models_rail_waitlist import (
    KIND_COMING_SOON,
    KIND_NATIONALITY_BLOCKED,
    LocalRailWaitlistEntry,
    resolve_waitlist_rail,
)

logger = logging.getLogger(__name__)


def _is_nationality_blocked(info, rail_id):
    """True only when the server itself refuses this rail for who the person is.

    Same account, identity and rail evaluation `localMoneyMethods` uses to
    list the row as blocked, so the label is never just the client's word.
    """
    from payment_accounts import local_money
    from payment_accounts.local_money_schema import _identity, _owner
    owner = _owner(info, 'view_balance')
    status, reason, _ = local_money.rail_status(
        owner, _identity(owner, required=False), local_money.METHODS[rail_id])
    return status == 'unavailable' and reason in local_money.IDENTITY_BLOCKED_REASONS


def _authenticated(info):
    user = getattr(info.context, 'user', None)
    return user if user is not None and getattr(user, 'is_authenticated', False) else None


class JoinLocalRailWaitlist(graphene.Mutation):
    """Join one rail's waitlist. Joining twice is a no-op, not an error."""

    class Arguments:
        rail_id = graphene.String(required=True)
        # 'coming_soon' (a "Próximamente" row) or 'nationality_blocked'.
        kind = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, rail_id, kind=KIND_COMING_SOON):
        user = _authenticated(info)
        if user is None:
            return cls(success=False, error='Inicia sesión para unirte a la lista.')
        rail_id = str(rail_id or '').strip()
        kind = str(kind or KIND_COMING_SOON).strip()
        parsed = resolve_waitlist_rail(rail_id, kind)
        if not parsed:
            return cls(success=False, error='Medio no reconocido.')
        direction, country = parsed
        if kind == KIND_NATIONALITY_BLOCKED:
            try:
                blocked = _is_nationality_blocked(info, rail_id)
            except Exception:
                # Unknown is not "blocked": refuse rather than guess.
                logger.exception('[rail_waitlist] blocked check failed rail=%s user=%s', rail_id, user.pk)
                blocked = False
            if not blocked:
                return cls(success=False, error='Este medio no está bloqueado para tu cuenta.')
        # get_or_create already absorbs a double-tap race on the unique
        # constraint; anything else it raises is a real failure, not a join.
        try:
            LocalRailWaitlistEntry.objects.get_or_create(
                user=user, rail_id=rail_id,
                defaults={'direction': direction, 'country': country, 'kind': kind},
            )
        except Exception:
            logger.exception('[rail_waitlist] join failed rail=%s user=%s', rail_id, user.pk)
            return cls(success=False, error='No pudimos anotarte. Intenta de nuevo.')
        return cls(success=True)


class LocalRailWaitlistMutations(graphene.ObjectType):
    join_local_rail_waitlist = JoinLocalRailWaitlist.Field()
