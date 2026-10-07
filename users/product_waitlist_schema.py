"""GraphQL for the paid-offer probes (Confío IA+, Cuenta inteligente).

Read: `paidOffers` says which doors this person sees, the price and whether
they're already on each list. Write: joining a list and answering its two
questions. The waitlist is per PERSON (like the rail waitlist): it keys on the
authenticated user and takes no account parameter; the JWT account is only
read to keep employees out and to record the account type.
"""
import logging

import graphene
from graphql_jwt.decorators import login_required

from users import paid_offers
from users.models_product_waitlist import (
    DOORS,
    PRODUCTS,
    TRIGGERS,
    VOLUME_RANGES,
    ProductWaitlistEntry,
)

logger = logging.getLogger(__name__)


def _who(info):
    """(user, is_employee, account_type) from the JWT context."""
    from assistant import service
    from inbox.schema import get_context_models

    user, account, business, jwt_context = get_context_models(info)
    viewer = service._viewer(user, account, business, jwt_context)
    return user, viewer.is_employee, viewer.account_type


def _authenticated(info):
    user = getattr(info.context, 'user', None)
    return user is not None and getattr(user, 'is_authenticated', False)


def _meta(info):
    return getattr(info.context, 'META', {}) or {}


def _last_chip_trigger(user, product):
    """Why the most recent chip for this offer was shown (last day), or ''."""
    from datetime import timedelta

    from django.utils import timezone

    from users.models import FunnelEvent
    event = FunnelEvent.objects.filter(
        event_name=paid_offers.EVENT, user=user, source_type=product,
        properties__stage='door_shown', properties__door='chip',
        created_at__gte=timezone.now() - timedelta(days=1),
    ).order_by('-created_at').first()
    trigger = str((event.properties or {}).get('trigger', '')) if event else ''
    return trigger if trigger in TRIGGERS else ''


class PaidOfferType(graphene.ObjectType):
    product = graphene.String(required=True, description="'ia_plus' or 'smart_account'")
    available = graphene.Boolean(required=True, description='The pitch can be opened (flag on, not an employee, new build)')
    row_visible = graphene.Boolean(required=True, description='Show the Billeteras row (Cuenta inteligente, ever funded)')
    monthly_price_usd = graphene.String(description='e.g. "9.99"; null hides the price line')
    on_waitlist = graphene.Boolean(required=True)
    waitlisted_at = graphene.DateTime()
    would_pay = graphene.String(description="'yes', 'no' or null when unanswered")
    volume_range = graphene.String(description='Cuenta inteligente volume answer, or null')


class PaidOfferQueries(graphene.ObjectType):
    paid_offers = graphene.List(graphene.NonNull(PaidOfferType), required=True)

    @login_required
    def resolve_paid_offers(self, info):
        from users.funding import has_funded

        try:
            user, is_employee, _ = _who(info)
        except Exception:  # noqa: BLE001 - no context, no doors
            logger.exception('paid offers: context failed')
            return []
        meta = _meta(info)
        entries = {e.product: e for e in ProductWaitlistEntry.objects.filter(user=user)}
        funded = None
        out = []
        for product in (paid_offers.PRODUCT_IA_PLUS, paid_offers.PRODUCT_SMART_ACCOUNT):
            available = paid_offers.available(product, is_employee=is_employee, meta=meta, user_id=user.pk)
            row = False
            if available and product == paid_offers.PRODUCT_SMART_ACCOUNT:
                funded = has_funded(user) if funded is None else funded
                row = funded
            entry = entries.get(product)
            out.append(PaidOfferType(
                product=product, available=available, row_visible=row,
                monthly_price_usd=paid_offers.price(product),
                on_waitlist=entry is not None,
                waitlisted_at=entry.created_at if entry else None,
                would_pay=(entry.would_pay or None) if entry else None,
                volume_range=(entry.volume_range or None) if entry else None,
            ))
        return out


class JoinPaidOfferWaitlist(graphene.Mutation):
    """Join one offer's waitlist ("Sí, avísame"). Joining twice is a no-op."""

    class Arguments:
        product = graphene.String(required=True)
        door = graphene.String(required=True)
        trigger = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    waitlisted_at = graphene.DateTime()
    already_listed = graphene.Boolean(description='True when this person was already on the list')

    @classmethod
    def mutate(cls, root, info, product, door, trigger=''):
        from users.funding import has_funded
        from users.funnel import emit_event

        if not _authenticated(info):
            return cls(success=False, error='Inicia sesión para unirte a la lista.')

        product, door, trigger = str(product or ''), str(door or ''), str(trigger or '')
        if product not in PRODUCTS or door not in DOORS or trigger not in TRIGGERS:
            return cls(success=False, error='Oferta no reconocida.')
        user, is_employee, account_type = _who(info)
        if not paid_offers.available(product, is_employee=is_employee, meta=_meta(info), user_id=user.pk):
            return cls(success=False, error='Esta oferta no está disponible.')
        if door == 'chip' and not trigger:
            # The chip's reason is known to the server (it logged the chip),
            # so the app never has to carry it.
            trigger = _last_chip_trigger(user, product)
        # get_or_create absorbs a double-tap race on the unique constraint;
        # anything else it raises is a real failure, never a silent "Listo".
        entry, created = ProductWaitlistEntry.objects.get_or_create(
            user=user, product=product,
            defaults={'door': door, 'trigger': trigger, 'account_type': account_type or '',
                      'funded': has_funded(user), 'country': (user.phone_country or '')[:2]},
        )
        if created:
            emit_event(paid_offers.EVENT, user=user, country=entry.country, source_type=product,
                       properties={'stage': 'avisame_tapped', 'offer': product, 'door': door,
                                   'trigger': trigger, 'account_type': entry.account_type,
                                   'funded': entry.funded})
        return cls(success=True, waitlisted_at=entry.created_at, already_listed=not created)


class AnswerPaidOffer(graphene.Mutation):
    """Save the would-pay and (Cuenta inteligente) volume answers."""

    class Arguments:
        product = graphene.String(required=True)
        would_pay = graphene.String(required=False)
        volume_range = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, product, would_pay=None, volume_range=None):
        from users.funnel import emit_event

        if not _authenticated(info):
            return cls(success=False, error='Inicia sesión.')

        product = str(product or '')
        if product not in PRODUCTS:
            return cls(success=False, error='Oferta no reconocida.')
        if would_pay not in (None, 'yes', 'no'):
            return cls(success=False, error='Respuesta no válida.')
        if volume_range is not None and (product != paid_offers.PRODUCT_SMART_ACCOUNT
                                         or volume_range not in VOLUME_RANGES):
            return cls(success=False, error='Respuesta no válida.')
        if would_pay is None and volume_range is None:
            return cls(success=False, error='Falta la respuesta.')
        user, is_employee, _ = _who(info)
        if not paid_offers.available(product, is_employee=is_employee, meta=_meta(info), user_id=user.pk):
            return cls(success=False, error='Esta oferta no está disponible.')
        entry = ProductWaitlistEntry.objects.filter(user=user, product=product).first()
        if entry is None:
            return cls(success=False, error='Primero toca "Sí, avísame".')
        fields = []
        if would_pay is not None:
            entry.would_pay = would_pay
            fields.append('would_pay')
        if volume_range is not None:
            entry.volume_range = volume_range
            fields.append('volume_range')
        entry.save(update_fields=fields + ['updated_at'])
        emit_event(paid_offers.EVENT, user=entry.user, country=entry.country, source_type=product,
                   properties={'stage': 'would_pay_answered' if would_pay is not None else 'volume_answered',
                               'offer': product, 'answer': would_pay or volume_range,
                               'door': entry.door, 'funded': entry.funded})
        return cls(success=True)


class PaidOfferMutations(graphene.ObjectType):
    join_paid_offer_waitlist = JoinPaidOfferWaitlist.Field()
    answer_paid_offer = AnswerPaidOffer.Field()
