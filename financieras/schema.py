"""
GraphQL schema for the Financieras directory.

Privacy: reviews are anonymous. FinancieraReviewType must never expose the
reviewer relation — it exists only for moderation and rate-limiting.

Country scoping: the directory defaults to the requesting user's phone country,
but clients may request another supported country for browsing.
"""

import logging
import unicodedata
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import graphene
import pycountry
from django.db.models import Case, Count, F, FloatField, Q, When
from django.utils import timezone
from graphene_django import DjangoObjectType

from .models import (
    COUNTRY_CHOICES,
    MIN_DISTINCT_RATE_REVIEWERS,
    Financiera,
    FinancieraReport,
    FinancieraReview,
)

logger = logging.getLogger(__name__)

VALID_COUNTRY_CODES = {code for code, _label in COUNTRY_CHOICES}

# A financiera always keeps a cut, so receiving more USD than USDC sent is
# implausible and almost certainly a typo that would poison the derived rate.
MAX_RECEIVED_RATIO = Decimal('1')
REVIEW_COOLDOWN = timedelta(hours=24)
# Reviews must reference a recent transaction so derived rates stay current.
REVIEWABLE_TX_MAX_AGE = timedelta(days=90)


class FinancieraReviewType(DjangoObjectType):
    direction = graphene.String(description="'sent' if user sold USDC/cUSD, 'received' if user bought")

    class Meta:
        model = FinancieraReview
        # Deliberately excludes 'reviewer' to keep reviews anonymous.
        fields = ('id', 'rating', 'sent_token', 'sent_usdc', 'received_usd', 'comment', 'created_at')

    def resolve_direction(self, info):
        if self.usdc_withdrawal_id:
            return 'sent'
        if self.send_transaction_id and self.send_transaction:
            return 'sent' if self.send_transaction.sender_user_id == self.reviewer_id else 'received'
        return 'sent'


class FinancieraType(DjangoObjectType):
    avg_rating = graphene.Float()
    review_count = graphene.Int()
    rate_review_count = graphene.Int(
        description='Sell-side reviews feeding the public rate; buy-side reviews count only for stars'
    )
    avg_received_per_100 = graphene.Float(
        description=(
            'Median USD received per 100 USDC sent, derived from reviews; '
            f'null until {MIN_DISTINCT_RATE_REVIEWERS}+ distinct verified users have reviewed'
        )
    )
    is_verified = graphene.Boolean()
    reviews = graphene.List(FinancieraReviewType, limit=graphene.Int(default_value=20))

    class Meta:
        model = Financiera
        fields = (
            'id', 'name', 'country_code', 'state', 'city', 'neighborhood',
            'whatsapp', 'supports_usdc_algorand', 'has_physical_location',
            'cash_usd', 'cash_local', 'digital_local',
            'helps_with_confio', 'home_service', 'open_weekends',
            'is_active', 'created_at',
        )

    def resolve_avg_rating(self, info):
        return self.avg_rating

    def resolve_review_count(self, info):
        return self.review_count

    def resolve_rate_review_count(self, info):
        return self.rate_review_count

    def resolve_avg_received_per_100(self, info):
        return self.avg_received_per_100

    def resolve_is_verified(self, info):
        return self.is_verified

    def resolve_reviews(self, info, limit):
        return self.reviews.order_by('-created_at')[: min(limit, 50)]


def _require_user(info):
    user = info.context.user
    if not user or not user.is_authenticated:
        return None
    return user


def _sort_key(name):
    """Accent-insensitive sort so 'Táchira' lands between Sucre and Trujillo."""
    return unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()


def _subdivision_names(country_code):
    """ISO 3166-2 subdivision names for a country, [] when ISO has none."""
    try:
        subdivisions = pycountry.subdivisions.get(country_code=country_code)
    except LookupError:
        return []
    if not subdivisions:
        return []
    return sorted((s.name for s in subdivisions), key=_sort_key)


def _collapse_ws(value):
    return ' '.join((value or '').split())


def _has_payout_method(cash_usd, cash_local, digital_local):
    return bool(cash_usd or cash_local or digital_local)


def _adopt_existing_casing(value, country_code, field, **scope):
    """Converge free-text locations on the first writer's spelling.

    If any active financiera in the same scope already has this value
    (case-insensitive), reuse its exact casing so the cascade filter never
    splits on 'chacao' vs 'Chacao'.
    """
    value = _collapse_ws(value)
    if not value:
        return value
    existing = (
        Financiera.objects.filter(
            country_code=country_code, deleted_at__isnull=True, **scope
        )
        .filter(**{f'{field}__iexact': value})
        .values_list(field, flat=True)
        .first()
    )
    return existing or value


class CountrySubdivisionType(graphene.ObjectType):
    name = graphene.String()


class FinancieraCountryType(graphene.ObjectType):
    """A country that currently has visible listings, for the country picker."""

    country_code = graphene.String()
    count = graphene.Int()


class ReviewableUsdcSendType(graphene.ObjectType):
    """A real dollar-stable transfer the user can attach a review to."""

    id = graphene.ID()
    kind = graphene.String(description="'send' (Confío transfer) or 'withdrawal' (external)")
    direction = graphene.String(description="'sent' or 'received'")
    token = graphene.String(description="'USDC' or 'CUSD' (withdrawals are always USDC)")
    amount_usdc = graphene.Decimal()
    destination = graphene.String(description='Counterparty/address, for recognition')
    created_at = graphene.DateTime()


class Query(graphene.ObjectType):
    financieras = graphene.List(
        FinancieraType,
        state=graphene.String(),
        city=graphene.String(),
        neighborhood=graphene.String(),
        country_code=graphene.String(
            description="Defaults to the user's phone country; override to browse another country"
        ),
        search=graphene.String(),
        sort_by=graphene.String(default_value='rating', description="'rating' or 'rate'"),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        description="Directory of financieras in a supported country",
    )
    financiera = graphene.Field(FinancieraType, id=graphene.ID(required=True))
    my_financieras = graphene.List(FinancieraType)
    financiera_location_options = graphene.List(
        graphene.String,
        level=graphene.String(required=True, description="'state', 'city' or 'neighborhood'"),
        state=graphene.String(),
        city=graphene.String(),
        country_code=graphene.String(
            description="Defaults to the user's country; override for registration autocomplete"
        ),
        description='Distinct location values for the cascade filter',
    )
    country_subdivisions = graphene.List(
        CountrySubdivisionType,
        country_code=graphene.String(required=True),
        description='ISO 3166-2 states/provinces for the registration picker',
    )
    my_reviewable_usdc_sends = graphene.List(
        ReviewableUsdcSendType,
        description='Recent confirmed USDC outflows not yet backing a review',
    )
    financiera_countries = graphene.List(
        FinancieraCountryType,
        description='Countries with visible financieras and their listing counts, '
                    'so the country picker can pin non-empty countries first',
    )

    def resolve_financiera_countries(self, info):
        user = _require_user(info)
        if not user:
            return []
        rows = (
            Financiera.objects.visible()
            .values('country_code')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        return [
            FinancieraCountryType(country_code=r['country_code'], count=r['count'])
            for r in rows
        ]

    def resolve_financieras(
        self, info, state=None, city=None, neighborhood=None, country_code=None, search=None,
        sort_by='rating', limit=50, offset=0,
    ):
        user = _require_user(info)
        if not user:
            return []
        country = (country_code or '').upper().strip() or user.phone_country
        if not country or country not in VALID_COUNTRY_CODES:
            return []

        qs = (
            Financiera.objects.visible()
            .filter(country_code=country)
            .with_stats()
        )
        if state:
            qs = qs.filter(state__iexact=state)
        if city:
            qs = qs.filter(city__iexact=city)
        if neighborhood:
            qs = qs.filter(neighborhood__iexact=neighborhood)
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(city__icontains=search)
                | Q(neighborhood__icontains=search)
                | Q(state__icontains=search)
            )

        if sort_by == 'rate':
            # Most dollars received per 100 USDC first. Listings whose rate is
            # still hidden (fewer distinct reviewers than the public threshold)
            # sort with the unreviewed ones, so a listing never ranks on a
            # number users can't see.
            qs = qs.annotate(
                public_ratio=Case(
                    When(
                        annotated_distinct_reviewers__gte=MIN_DISTINCT_RATE_REVIEWERS,
                        then=F('annotated_median_ratio'),
                    ),
                    output_field=FloatField(),
                )
            ).order_by(F('public_ratio').desc(nulls_last=True))
        else:
            qs = qs.order_by(F('annotated_avg_rating').desc(nulls_last=True))

        return qs[offset: offset + min(limit, 100)]

    def resolve_financiera(self, info, id):
        user = _require_user(info)
        if not user:
            return None
        try:
            return Financiera.objects.visible().with_stats().get(pk=id)
        except Financiera.DoesNotExist:
            return None

    def resolve_my_financieras(self, info):
        user = _require_user(info)
        if not user:
            return []
        return Financiera.objects.filter(owner=user, deleted_at__isnull=True).with_stats()

    def resolve_financiera_location_options(self, info, level, state=None, city=None, country_code=None):
        user = _require_user(info)
        if not user:
            return []
        country = (country_code or '').upper().strip() or user.phone_country
        if not country or level not in ('state', 'city', 'neighborhood'):
            return []
        qs = Financiera.objects.visible().filter(country_code=country)
        if state:
            qs = qs.filter(state__iexact=state)
        if city:
            qs = qs.filter(city__iexact=city)
        return (
            qs.exclude(**{level: ''})
            .values_list(level, flat=True)
            .distinct()
            .order_by(level)
        )

    def resolve_country_subdivisions(self, info, country_code):
        # Static ISO data; no auth or country scoping needed.
        return [
            CountrySubdivisionType(name=name)
            for name in _subdivision_names(country_code.upper().strip())
        ]

    def resolve_my_reviewable_usdc_sends(self, info):
        from send.models import SendTransaction
        from usdc_transactions.models import USDCWithdrawal

        user = _require_user(info)
        if not user:
            return []
        cutoff = timezone.now() - REVIEWABLE_TX_MAX_AGE

        used_sends = FinancieraReview.objects.filter(
            send_transaction__isnull=False
        ).values_list('send_transaction_id', flat=True)
        sends = (
            SendTransaction.objects.filter(
                Q(sender_user=user) | Q(recipient_user=user),
                token_type__in=REVIEWABLE_SEND_TOKENS,
                status='CONFIRMED',
                deleted_at__isnull=True,
                created_at__gte=cutoff,
            )
            .exclude(pk__in=used_sends)
            .order_by('-created_at')[:20]
        )

        used_withdrawals = FinancieraReview.objects.filter(
            usdc_withdrawal__isnull=False
        ).values_list('usdc_withdrawal_id', flat=True)
        withdrawals = USDCWithdrawal.objects.filter(
            actor_user=user,
            status='COMPLETED',
            created_at__gte=cutoff,
        ).exclude(pk__in=used_withdrawals).order_by('-created_at')[:20]

        items = [
            ReviewableUsdcSendType(
                id=tx.pk,
                kind='send',
                direction='sent' if tx.sender_user_id == user.id else 'received',
                token=tx.token_type,
                amount_usdc=tx.amount,
                destination=(
                    tx.recipient_address if tx.sender_user_id == user.id else tx.sender_address
                ) or '',
                created_at=tx.created_at,
            )
            for tx in sends
        ] + [
            ReviewableUsdcSendType(
                id=w.pk, kind='withdrawal', direction='sent', token='USDC', amount_usdc=w.amount,
                destination=w.destination_address or '', created_at=w.created_at,
            )
            for w in withdrawals
        ]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items[:20]


class RegisterFinanciera(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        country_code = graphene.String(required=True)
        state = graphene.String(required=True)
        city = graphene.String(required=True)
        neighborhood = graphene.String()
        whatsapp = graphene.String(required=True, description='Digits-only E.164 without +')
        supports_usdc_algorand = graphene.Boolean(required=True)
        has_physical_location = graphene.Boolean(default_value=True)
        cash_usd = graphene.Boolean(default_value=True)
        cash_local = graphene.Boolean(default_value=False)
        digital_local = graphene.Boolean(default_value=False)
        helps_with_confio = graphene.Boolean(default_value=False)
        home_service = graphene.Boolean(default_value=False)
        open_weekends = graphene.Boolean(default_value=False)

    success = graphene.Boolean()
    error = graphene.String()
    financiera = graphene.Field(FinancieraType)

    def mutate(
        self, info, name, country_code, state, city, whatsapp,
        supports_usdc_algorand, neighborhood='', helps_with_confio=False,
        home_service=False, open_weekends=False, has_physical_location=True,
        cash_usd=True, cash_local=False, digital_local=False,
    ):
        user = _require_user(info)
        if not user:
            return RegisterFinanciera(success=False, error='Debes iniciar sesión.')
        if not user.is_identity_verified:
            return RegisterFinanciera(
                success=False,
                error='Debes verificar tu identidad para registrar una financiera.',
            )
        # Mandatory at launch: USDC over Algorand is the only supported rail.
        if not supports_usdc_algorand:
            return RegisterFinanciera(
                success=False,
                error='Para registrarte debes aceptar USDC por la red Algorand.',
            )
        country_code = (country_code or '').upper().strip()
        if country_code not in VALID_COUNTRY_CODES:
            return RegisterFinanciera(success=False, error='País inválido.')
        whatsapp = ''.join(ch for ch in whatsapp if ch.isdigit())
        if not (8 <= len(whatsapp) <= 15):
            return RegisterFinanciera(success=False, error='Número de WhatsApp inválido.')
        name = _collapse_ws(name)
        if not name:
            return RegisterFinanciera(success=False, error='El nombre es obligatorio.')
        if not _has_payout_method(cash_usd, cash_local, digital_local):
            return RegisterFinanciera(
                success=False,
                error='Selecciona al menos una forma de entrega.',
            )

        # Estado/provincia must be an ISO 3166-2 subdivision when ISO covers the
        # country (it does for all of LATAM); free text only as a fallback for
        # territories without subdivisions. Matching is accent/case-insensitive
        # and the canonical ISO spelling is what gets stored.
        state = _collapse_ws(state)
        subdivision_names = _subdivision_names(country_code)
        if subdivision_names:
            canonical = next(
                (n for n in subdivision_names if _sort_key(n) == _sort_key(state)), None
            )
            if canonical is None:
                return RegisterFinanciera(
                    success=False, error='Selecciona un estado o provincia válido.'
                )
            state = canonical

        # City/barrio are free text that converge on the first writer's spelling.
        city = _adopt_existing_casing(city, country_code, 'city', state__iexact=state)
        neighborhood = _adopt_existing_casing(
            neighborhood, country_code, 'neighborhood', state__iexact=state, city__iexact=city
        )
        if not city:
            return RegisterFinanciera(success=False, error='La ciudad es obligatoria.')

        if Financiera.objects.filter(
            owner=user, name__iexact=name, city__iexact=city, deleted_at__isnull=True
        ).exists():
            return RegisterFinanciera(
                success=False, error='Ya registraste una financiera con ese nombre en esa ciudad.'
            )

        financiera = Financiera.objects.create(
            owner=user,
            name=name,
            country_code=country_code,
            state=state,
            city=city,
            neighborhood=neighborhood,
            whatsapp=whatsapp,
            supports_usdc_algorand=True,
            has_physical_location=has_physical_location,
            cash_usd=cash_usd,
            cash_local=cash_local,
            digital_local=digital_local,
            helps_with_confio=helps_with_confio,
            home_service=home_service,
            open_weekends=open_weekends,
        )
        logger.info('Financiera %s registered by user %s', financiera.id, user.id)
        return RegisterFinanciera(success=True, financiera=financiera)


def _get_owned_financiera(info, financiera_id):
    """Resolve a financiera the requesting user owns, or (None, error)."""
    user = _require_user(info)
    if not user:
        return None, 'Debes iniciar sesión.'
    try:
        financiera = Financiera.objects.get(pk=financiera_id, deleted_at__isnull=True)
    except Financiera.DoesNotExist:
        return None, 'Financiera no encontrada.'
    if financiera.owner_id != user.id:
        return None, 'Solo el dueño puede gestionar esta financiera.'
    return financiera, None


class UpdateFinanciera(graphene.Mutation):
    """Owner edits to a listing. Country is fixed (delete + re-register to move
    countries) and supports_usdc_algorand stays mandatory, so neither is editable."""

    class Arguments:
        financiera_id = graphene.ID(required=True)
        name = graphene.String()
        state = graphene.String()
        city = graphene.String()
        neighborhood = graphene.String()
        whatsapp = graphene.String()
        has_physical_location = graphene.Boolean()
        cash_usd = graphene.Boolean()
        cash_local = graphene.Boolean()
        digital_local = graphene.Boolean()
        helps_with_confio = graphene.Boolean()
        home_service = graphene.Boolean()
        open_weekends = graphene.Boolean()

    success = graphene.Boolean()
    error = graphene.String()
    financiera = graphene.Field(FinancieraType)

    def mutate(
        self, info, financiera_id, name=None, state=None, city=None,
        neighborhood=None, whatsapp=None, helps_with_confio=None,
        home_service=None, open_weekends=None, has_physical_location=None,
        cash_usd=None, cash_local=None, digital_local=None,
    ):
        financiera, error = _get_owned_financiera(info, financiera_id)
        if error:
            return UpdateFinanciera(success=False, error=error)

        if name is not None:
            name = _collapse_ws(name)
            if not name:
                return UpdateFinanciera(success=False, error='El nombre es obligatorio.')
            financiera.name = name

        if state is not None:
            state = _collapse_ws(state)
            subdivision_names = _subdivision_names(financiera.country_code)
            if subdivision_names:
                canonical = next(
                    (n for n in subdivision_names if _sort_key(n) == _sort_key(state)), None
                )
                if canonical is None:
                    return UpdateFinanciera(
                        success=False, error='Selecciona un estado o provincia válido.'
                    )
                state = canonical
            financiera.state = state

        if city is not None:
            city = _adopt_existing_casing(
                city, financiera.country_code, 'city', state__iexact=financiera.state
            )
            if not city:
                return UpdateFinanciera(success=False, error='La ciudad es obligatoria.')
            financiera.city = city

        if neighborhood is not None:
            financiera.neighborhood = _adopt_existing_casing(
                neighborhood, financiera.country_code, 'neighborhood',
                state__iexact=financiera.state, city__iexact=financiera.city,
            )

        if whatsapp is not None:
            whatsapp = ''.join(ch for ch in whatsapp if ch.isdigit())
            if not (8 <= len(whatsapp) <= 15):
                return UpdateFinanciera(success=False, error='Número de WhatsApp inválido.')
            financiera.whatsapp = whatsapp

        if has_physical_location is not None:
            financiera.has_physical_location = has_physical_location
        if cash_usd is not None:
            financiera.cash_usd = cash_usd
        if cash_local is not None:
            financiera.cash_local = cash_local
        if digital_local is not None:
            financiera.digital_local = digital_local
        if not _has_payout_method(
            financiera.cash_usd,
            financiera.cash_local,
            financiera.digital_local,
        ):
            return UpdateFinanciera(
                success=False,
                error='Selecciona al menos una forma de entrega.',
            )

        if helps_with_confio is not None:
            financiera.helps_with_confio = helps_with_confio
        if home_service is not None:
            financiera.home_service = home_service
        if open_weekends is not None:
            financiera.open_weekends = open_weekends

        if Financiera.objects.filter(
            owner=financiera.owner, name__iexact=financiera.name,
            city__iexact=financiera.city, deleted_at__isnull=True,
        ).exclude(pk=financiera.pk).exists():
            return UpdateFinanciera(
                success=False, error='Ya tienes una financiera con ese nombre en esa ciudad.'
            )

        financiera.save()
        logger.info('Financiera %s updated by owner', financiera.id)
        return UpdateFinanciera(success=True, financiera=financiera)


class SetFinancieraActive(graphene.Mutation):
    """Pause/unpause a listing (e.g. vacations) without losing its reviews."""

    class Arguments:
        financiera_id = graphene.ID(required=True)
        is_active = graphene.Boolean(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    financiera = graphene.Field(FinancieraType)

    def mutate(self, info, financiera_id, is_active):
        financiera, error = _get_owned_financiera(info, financiera_id)
        if error:
            return SetFinancieraActive(success=False, error=error)
        financiera.is_active = is_active
        financiera.save(update_fields=['is_active', 'updated_at'])
        logger.info('Financiera %s set active=%s by owner', financiera.id, is_active)
        return SetFinancieraActive(success=True, financiera=financiera)


class DeleteFinanciera(graphene.Mutation):
    class Arguments:
        financiera_id = graphene.ID(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, financiera_id):
        financiera, error = _get_owned_financiera(info, financiera_id)
        if error:
            return DeleteFinanciera(success=False, error=error)
        financiera.delete()  # SoftDeleteModel: sets deleted_at
        logger.info('Financiera %s soft-deleted by owner', financiera.id)
        return DeleteFinanciera(success=True)


# Within-app transfers can be in cUSD too — it's the app's main balance, so a
# financiera on Confío usually receives cUSD. Both tokens are $1-pegged, so the
# derived rate math is identical. External withdrawals are USDC by nature.
REVIEWABLE_SEND_TOKENS = ('USDC', 'CUSD')


def _resolve_backing_transaction(user, send_transaction_id, usdc_withdrawal_id):
    """Resolve and validate the transaction a review claims to be about.

    Returns (send_tx, withdrawal, sent_amount, sent_token, direction, error).
    Exactly one reference is required; the transaction must be the user's own
    confirmed dollar-stable transfer, recent enough to review, and not already
    backing another review.
    """
    from send.models import SendTransaction
    from usdc_transactions.models import USDCWithdrawal

    if bool(send_transaction_id) == bool(usdc_withdrawal_id):
        return None, None, None, None, None, 'Selecciona la transacción que respalda tu reseña.'

    cutoff = timezone.now() - REVIEWABLE_TX_MAX_AGE
    if send_transaction_id:
        tx = SendTransaction.objects.filter(
            pk=send_transaction_id,
            token_type__in=REVIEWABLE_SEND_TOKENS,
            status='CONFIRMED',
            deleted_at__isnull=True,
        ).filter(
            Q(sender_user=user) | Q(recipient_user=user),
        ).first()
        if not tx:
            return None, None, None, None, None, 'No encontramos esa transacción en tu cuenta.'
        if tx.created_at < cutoff:
            return None, None, None, None, None, 'Esa transacción es muy antigua para reseñar (máx. 90 días).'
        if FinancieraReview.objects.filter(send_transaction=tx).exists():
            return None, None, None, None, None, 'Esa transacción ya respalda otra reseña.'
        return (
            tx,
            None,
            tx.amount,
            tx.token_type,
            'sent' if tx.sender_user_id == user.id else 'received',
            None,
        )

    withdrawal = USDCWithdrawal.objects.filter(
        pk=usdc_withdrawal_id,
        actor_user=user,
        status='COMPLETED',
    ).first()
    if not withdrawal:
        return None, None, None, None, None, 'No encontramos ese retiro de USDC en tu cuenta.'
    if withdrawal.created_at < cutoff:
        return None, None, None, None, None, 'Ese retiro es muy antiguo para reseñar (máx. 90 días).'
    if FinancieraReview.objects.filter(usdc_withdrawal=withdrawal).exists():
        return None, None, None, None, None, 'Ese retiro ya respalda otra reseña.'
    return None, withdrawal, withdrawal.amount, 'USDC', 'sent', None


class SubmitFinancieraReview(graphene.Mutation):
    """Reviews must be anchored to a real USDC-Algorand transaction. The
    transaction amount comes from the server, never from the client."""

    class Arguments:
        financiera_id = graphene.ID(required=True)
        rating = graphene.Int(required=True)
        received_usd = graphene.Decimal(required=True)
        comment = graphene.String()
        send_transaction_id = graphene.ID(
            description='Confirmed USDC send backing this review'
        )
        usdc_withdrawal_id = graphene.ID(
            description='Completed USDC withdrawal backing this review'
        )

    success = graphene.Boolean()
    error = graphene.String()
    review = graphene.Field(FinancieraReviewType)

    def mutate(
        self, info, financiera_id, rating, received_usd, comment='',
        send_transaction_id=None, usdc_withdrawal_id=None,
    ):
        user = _require_user(info)
        if not user:
            return SubmitFinancieraReview(success=False, error='Debes iniciar sesión.')
        if not user.is_identity_verified:
            return SubmitFinancieraReview(
                success=False, error='Debes verificar tu identidad para dejar reseñas.'
            )
        try:
            financiera = Financiera.objects.visible().get(pk=financiera_id)
        except Financiera.DoesNotExist:
            return SubmitFinancieraReview(success=False, error='Financiera no encontrada.')
        if financiera.owner_id == user.id:
            return SubmitFinancieraReview(
                success=False, error='No puedes reseñar tu propia financiera.'
            )
        if not (1 <= rating <= 5):
            return SubmitFinancieraReview(success=False, error='La calificación debe ser de 1 a 5.')

        send_tx, withdrawal, sent, sent_token, direction, error = _resolve_backing_transaction(
            user, send_transaction_id, usdc_withdrawal_id
        )
        if error:
            return SubmitFinancieraReview(success=False, error=error)

        try:
            received = Decimal(received_usd)
        except (InvalidOperation, TypeError):
            return SubmitFinancieraReview(success=False, error='Monto inválido.')
        if received <= 0:
            return SubmitFinancieraReview(success=False, error='El monto debe ser mayor a cero.')
        # Hard plausibility gate for sell/outflow reviews. Buy-side reviews are
        # valid reputation signals, but they do not feed the public cash-out
        # rate because the user may pay more fiat than the USDC/cUSD received.
        if direction == 'sent' and received > sent * MAX_RECEIVED_RATIO:
            return SubmitFinancieraReview(
                success=False,
                error='El monto no puede ser mayor que la transacción en USDC/cUSD. Revisa el monto.',
            )
        recent = FinancieraReview.objects.filter(
            financiera=financiera,
            reviewer=user,
            created_at__gte=timezone.now() - REVIEW_COOLDOWN,
        ).exists()
        if recent:
            return SubmitFinancieraReview(
                success=False,
                error='Ya dejaste una reseña para esta financiera hoy. Intenta mañana.',
            )

        review = FinancieraReview.objects.create(
            financiera=financiera,
            reviewer=user,
            send_transaction=send_tx,
            usdc_withdrawal=withdrawal,
            rating=rating,
            sent_token=sent_token,
            sent_usdc=sent,
            received_usd=received,
            comment=(comment or '').strip()[:280],
        )
        logger.info('Review %s created for financiera %s', review.id, financiera.id)
        return SubmitFinancieraReview(success=True, review=review)


class ReportFinanciera(graphene.Mutation):
    class Arguments:
        financiera_id = graphene.ID(required=True)
        reason = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, financiera_id, reason):
        user = _require_user(info)
        if not user:
            return ReportFinanciera(success=False, error='Debes iniciar sesión.')
        # A report the moderation team can't act on is noise — require substance.
        reason = ' '.join((reason or '').split())
        if len(reason) < 10:
            return ReportFinanciera(
                success=False,
                error='Cuéntanos qué pasó (mínimo 10 caracteres) para poder revisarlo.',
            )
        try:
            financiera = Financiera.objects.visible().get(pk=financiera_id)
        except Financiera.DoesNotExist:
            return ReportFinanciera(success=False, error='Financiera no encontrada.')
        FinancieraReport.objects.create(
            financiera=financiera,
            reporter=user,
            reason=reason[:500],
        )
        logger.info('Report created for financiera %s by user %s', financiera.id, user.id)
        return ReportFinanciera(success=True)


class Mutation(graphene.ObjectType):
    register_financiera = RegisterFinanciera.Field()
    update_financiera = UpdateFinanciera.Field()
    set_financiera_active = SetFinancieraActive.Field()
    delete_financiera = DeleteFinanciera.Field()
    submit_financiera_review = SubmitFinancieraReview.Field()
    report_financiera = ReportFinanciera.Field()
