"""
GraphQL schema for the Financieras directory.

Privacy: reviews are anonymous. FinancieraReviewType must never expose the
reviewer relation — it exists only for moderation and rate-limiting.

Country scoping: the directory always serves the requesting user's country
(from their JWT-authenticated profile), never a client-supplied country.
"""

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import graphene
from django.db.models import F, Q
from django.utils import timezone
from graphene_django import DjangoObjectType

from .models import COUNTRY_CHOICES, Financiera, FinancieraReport, FinancieraReview

logger = logging.getLogger(__name__)

VALID_COUNTRY_CODES = {code for code, _label in COUNTRY_CHOICES}

# A financiera always keeps a cut, so receiving more USD than USDC sent is
# implausible and almost certainly a typo that would poison the derived rate.
MAX_RECEIVED_RATIO = Decimal('1')
REVIEW_COOLDOWN = timedelta(hours=24)


class FinancieraReviewType(DjangoObjectType):
    class Meta:
        model = FinancieraReview
        # Deliberately excludes 'reviewer' to keep reviews anonymous.
        fields = ('id', 'rating', 'sent_usdc', 'received_usd', 'comment', 'created_at')


class FinancieraType(DjangoObjectType):
    avg_rating = graphene.Float()
    review_count = graphene.Int()
    avg_received_per_100 = graphene.Float(
        description='Average USD received per 100 USDC sent, derived from reviews'
    )
    is_verified = graphene.Boolean()
    reviews = graphene.List(FinancieraReviewType, limit=graphene.Int(default_value=20))

    class Meta:
        model = Financiera
        fields = (
            'id', 'name', 'country_code', 'state', 'city', 'neighborhood',
            'whatsapp', 'supports_usdc_algorand', 'helps_with_confio',
            'home_service', 'open_weekends', 'created_at',
        )

    def resolve_avg_rating(self, info):
        return self.avg_rating

    def resolve_review_count(self, info):
        return self.review_count

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


class Query(graphene.ObjectType):
    financieras = graphene.List(
        FinancieraType,
        state=graphene.String(),
        city=graphene.String(),
        neighborhood=graphene.String(),
        search=graphene.String(),
        sort_by=graphene.String(default_value='rating', description="'rating' or 'rate'"),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        description="Directory of financieras in the requesting user's country",
    )
    financiera = graphene.Field(FinancieraType, id=graphene.ID(required=True))
    my_financieras = graphene.List(FinancieraType)
    financiera_location_options = graphene.List(
        graphene.String,
        level=graphene.String(required=True, description="'state', 'city' or 'neighborhood'"),
        state=graphene.String(),
        city=graphene.String(),
        description='Distinct location values for the cascade filter',
    )

    def resolve_financieras(
        self, info, state=None, city=None, neighborhood=None, search=None,
        sort_by='rating', limit=50, offset=0,
    ):
        user = _require_user(info)
        if not user or not user.phone_country:
            return []

        qs = (
            Financiera.objects.visible()
            .filter(country_code=user.phone_country)
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
            # Most dollars received per 100 USDC first; unreviewed listings last.
            qs = qs.order_by(F('annotated_avg_ratio').desc(nulls_last=True))
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

    def resolve_financiera_location_options(self, info, level, state=None, city=None):
        user = _require_user(info)
        if not user or not user.phone_country:
            return []
        if level not in ('state', 'city', 'neighborhood'):
            return []
        qs = Financiera.objects.visible().filter(country_code=user.phone_country)
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


class RegisterFinanciera(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        country_code = graphene.String(required=True)
        state = graphene.String(required=True)
        city = graphene.String(required=True)
        neighborhood = graphene.String()
        whatsapp = graphene.String(required=True, description='Digits-only E.164 without +')
        supports_usdc_algorand = graphene.Boolean(required=True)
        helps_with_confio = graphene.Boolean(default_value=False)
        home_service = graphene.Boolean(default_value=False)
        open_weekends = graphene.Boolean(default_value=False)

    success = graphene.Boolean()
    error = graphene.String()
    financiera = graphene.Field(FinancieraType)

    def mutate(
        self, info, name, country_code, state, city, whatsapp,
        supports_usdc_algorand, neighborhood='', helps_with_confio=False,
        home_service=False, open_weekends=False,
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
        name = name.strip()
        if not name:
            return RegisterFinanciera(success=False, error='El nombre es obligatorio.')
        if Financiera.objects.filter(
            owner=user, name__iexact=name, city__iexact=city.strip(), deleted_at__isnull=True
        ).exists():
            return RegisterFinanciera(
                success=False, error='Ya registraste una financiera con ese nombre en esa ciudad.'
            )

        financiera = Financiera.objects.create(
            owner=user,
            name=name,
            country_code=country_code,
            state=state.strip(),
            city=city.strip(),
            neighborhood=(neighborhood or '').strip(),
            whatsapp=whatsapp,
            supports_usdc_algorand=True,
            helps_with_confio=helps_with_confio,
            home_service=home_service,
            open_weekends=open_weekends,
        )
        logger.info('Financiera %s registered by user %s', financiera.id, user.id)
        return RegisterFinanciera(success=True, financiera=financiera)


class SubmitFinancieraReview(graphene.Mutation):
    class Arguments:
        financiera_id = graphene.ID(required=True)
        rating = graphene.Int(required=True)
        sent_usdc = graphene.Decimal(required=True)
        received_usd = graphene.Decimal(required=True)
        comment = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()
    review = graphene.Field(FinancieraReviewType)

    def mutate(self, info, financiera_id, rating, sent_usdc, received_usd, comment=''):
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
        try:
            sent = Decimal(sent_usdc)
            received = Decimal(received_usd)
        except (InvalidOperation, TypeError):
            return SubmitFinancieraReview(success=False, error='Montos inválidos.')
        if sent <= 0 or received <= 0:
            return SubmitFinancieraReview(success=False, error='Los montos deben ser mayores a cero.')
        # Hard plausibility gate: these amounts feed the public derived rate.
        if received > sent * MAX_RECEIVED_RATIO:
            return SubmitFinancieraReview(
                success=False,
                error='No puedes recibir más dólares de los USDC que enviaste. Revisa los montos.',
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
            rating=rating,
            sent_usdc=sent,
            received_usd=received,
            comment=(comment or '').strip()[:280],
        )
        logger.info('Review %s created for financiera %s', review.id, financiera.id)
        return SubmitFinancieraReview(success=True, review=review)


class ReportFinanciera(graphene.Mutation):
    class Arguments:
        financiera_id = graphene.ID(required=True)
        reason = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, financiera_id, reason=''):
        user = _require_user(info)
        if not user:
            return ReportFinanciera(success=False, error='Debes iniciar sesión.')
        try:
            financiera = Financiera.objects.visible().get(pk=financiera_id)
        except Financiera.DoesNotExist:
            return ReportFinanciera(success=False, error='Financiera no encontrada.')
        FinancieraReport.objects.create(
            financiera=financiera,
            reporter=user,
            reason=(reason or '').strip()[:500],
        )
        logger.info('Report created for financiera %s by user %s', financiera.id, user.id)
        return ReportFinanciera(success=True)


class Mutation(graphene.ObjectType):
    register_financiera = RegisterFinanciera.Field()
    submit_financiera_review = SubmitFinancieraReview.Field()
    report_financiera = ReportFinanciera.Field()
