import graphene
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from graphql_jwt.decorators import login_required
from graphql import GraphQLError
from users.jwt_context import get_jwt_business_context_with_validation
from users.models import Account

from .identity_tokens import InvalidInstitutionToken, consume_identity_token
from .member_payments import MemberCheckoutError, create_member_payment_intent
from .models import BillingObligation, InstitutionApplication, InstitutionIdentitySession, ObligationSubject


class MemberObligationType(graphene.ObjectType):
    id = graphene.NonNull(graphene.String)
    institution_name = graphene.NonNull(graphene.String)
    member_reference = graphene.NonNull(graphene.String)
    amount_minor = graphene.NonNull(graphene.BigInt)
    amount_remaining_minor = graphene.NonNull(graphene.BigInt)
    currency = graphene.NonNull(graphene.String)
    period_key = graphene.String()
    period_start = graphene.NonNull(graphene.Date)
    period_end = graphene.NonNull(graphene.Date)
    due_at = graphene.NonNull(graphene.DateTime)
    status = graphene.NonNull(graphene.String)
    description = graphene.String()
    institution_application_status = graphene.String()
    institution_member_status = graphene.String()
    institution_applied_at = graphene.DateTime()


class MemberBillingEntryType(graphene.ObjectType):
    id = graphene.NonNull(graphene.String)
    institution_name = graphene.NonNull(graphene.String)
    period_start = graphene.NonNull(graphene.Date)
    due_at = graphene.NonNull(graphene.DateTime)
    amount_remaining_minor = graphene.NonNull(graphene.BigInt)
    currency = graphene.NonNull(graphene.String)
    status = graphene.NonNull(graphene.String)
    application_status = graphene.String()


class MemberBillingSummaryType(graphene.ObjectType):
    linked = graphene.NonNull(graphene.Boolean)
    open_count = graphene.NonNull(graphene.Int)
    total_due_minor = graphene.NonNull(graphene.BigInt)
    currency = graphene.NonNull(graphene.String)
    entry = graphene.Field(MemberBillingEntryType)


def _member_obligations(user):
    return (
        BillingObligation.objects.filter(subject__confio_user=user)
        .select_related('business', 'subject')
        .order_by('-period_start', '-id')
    )


def _member_context(info, permission=None):
    context = get_jwt_business_context_with_validation(info, required_permission=permission)
    if not context:
        raise GraphQLError('permission_denied')
    return context


class Query(graphene.ObjectType):
    my_billing_obligations = graphene.NonNull(graphene.List(graphene.NonNull(MemberObligationType)))
    my_billing_summary = graphene.NonNull(MemberBillingSummaryType)

    @login_required
    def resolve_my_billing_obligations(self, info):
        _member_context(info)
        obligations = list(_member_obligations(info.context.user))
        applications = {}
        # An unresolved application must stay visible even if a later partial
        # allocation was acknowledged. Only expose an allowlisted member state,
        # never arbitrary connector response strings or identifying references.
        priorities = {'acknowledged': 0, 'payment_confirmed': 1, 'application_pending': 2,
                      'retry_scheduled': 3, 'mismatch': 4, 'rejected': 5}
        for application in InstitutionApplication.objects.filter(
                allocation__obligation_id__in=[row.id for row in obligations],
                allocation__commercial_delta_minor__gt=0,
                billing_payment__status='confirmed').select_related('allocation').order_by('id'):
            key = application.allocation.obligation_id
            prior = applications.get(key)
            if prior is None or priorities.get(application.status, 3) >= priorities.get(prior.status, 3):
                applications[key] = application

        def application_fields(row):
            application = applications.get(row.id)
            if not application:
                return {}
            acknowledged = application.status == 'acknowledged'
            member_status = application.returned_status if acknowledged else None
            return {
                'institution_application_status': application.status,
                'institution_member_status': member_status if member_status in (
                    'active', 'inactive', 'habil', 'inhabil') else None,
                'institution_applied_at': application.institution_applied_at if acknowledged else None,
            }
        return [
            MemberObligationType(
                id=row.public_id,
                institution_name=row.business.name,
                member_reference=row.subject.masked_reference or 'Membresía vinculada',
                amount_minor=row.original_amount_minor,
                amount_remaining_minor=row.amount_remaining_minor,
                currency=row.currency,
                period_key=row.period_key or None,
                period_start=row.period_start,
                period_end=row.period_end,
                due_at=row.due_at,
                status=row.status,
                description=(row.line_items_snapshot[0].get('description', '')
                             if row.line_items_snapshot else ''),
                **application_fields(row),
            ) for row in obligations
        ]

    @login_required
    def resolve_my_billing_summary(self, info):
        _member_context(info)
        rows = _member_obligations(info.context.user)
        linked = ObligationSubject.objects.filter(confio_user=info.context.user).exists()
        payable = rows.filter(status__in=('open', 'past_due', 'payment_pending'))
        modes = []
        if getattr(settings, 'BILLING_LIVE_API_KEYS_ENABLED', False):
            modes.append('live')
        if getattr(settings, 'BILLING_CIP_SANDBOX_ENABLED', False):
            modes.append('test')
        eligible = rows.filter(subject__mode__in=modes, subject__status='active',
                               business__deleted_at__isnull=True)
        # Pending institution acknowledgment takes precedence over another bill:
        # never encourage repayment of a confirmed payment.
        application = InstitutionApplication.objects.filter(
            allocation__obligation__in=eligible.filter(status='paid'),
            allocation__commercial_delta_minor__gt=0,
            billing_payment__status='confirmed',
        ).exclude(status='acknowledged').select_related(
            'allocation__obligation__business').order_by('created_at', 'id').first()
        row = application.allocation.obligation if application else eligible.filter(
            status__in=('open', 'past_due', 'payment_pending'),
            amount_remaining_minor__gt=0).order_by('due_at', 'id').first()
        entry = MemberBillingEntryType(
            id=row.public_id, institution_name=row.business.name,
            period_start=row.period_start, due_at=row.due_at,
            amount_remaining_minor=row.amount_remaining_minor, currency=row.currency,
            status=row.status, application_status=application.status if application else None,
        ) if row else None
        return MemberBillingSummaryType(
            linked=linked, open_count=payable.count(),
            total_due_minor=sum(payable.values_list('amount_remaining_minor', flat=True)),
            currency='PEN',
            entry=entry,
        )


class CreateMemberPaymentIntent(graphene.Mutation):
    class Arguments:
        obligation_id = graphene.NonNull(graphene.String)

    success = graphene.NonNull(graphene.Boolean)
    invoice_id = graphene.String()
    expires_at = graphene.DateTime()
    errors = graphene.NonNull(graphene.List(graphene.NonNull(graphene.String)))

    @classmethod
    @login_required
    def mutate(cls, root, info, obligation_id):
        context = _member_context(info, 'send_funds')
        accounts = Account.objects.filter(
            account_type=context['account_type'],
            account_index=context.get('account_index', 0), deleted_at__isnull=True)
        if context['account_type'] == 'business':
            accounts = accounts.filter(business_id=context.get('business_id'))
        else:
            accounts = accounts.filter(user=info.context.user)
        payer_account = accounts.first()
        if payer_account is None:
            return cls(success=False, errors=['account_not_found'])
        try:
            intent = create_member_payment_intent(
                obligation_public_id=obligation_id, user=info.context.user,
                payer_account=payer_account)
            return cls(success=True, invoice_id=intent.legacy_invoice.internal_id,
                       expires_at=intent.expires_at, errors=[])
        except BillingObligation.DoesNotExist:
            return cls(success=False, errors=['obligation_not_found'])
        except MemberCheckoutError as exc:
            return cls(success=False, errors=[str(exc)])


class ClaimInstitutionMembership(graphene.Mutation):
    """Link the signed-in user without accepting raw DNI or other identity data."""

    class Arguments:
        provider = graphene.NonNull(graphene.String)
        token = graphene.NonNull(graphene.String)

    success = graphene.NonNull(graphene.Boolean)
    errors = graphene.NonNull(graphene.List(graphene.NonNull(graphene.String)))

    @classmethod
    @login_required
    def mutate(cls, root, info, provider, token):
        _member_context(info)
        try:
            with transaction.atomic():
                session, _ = consume_identity_token(token, provider=provider)
                session = InstitutionIdentitySession.objects.select_for_update().get(pk=session.pk)
                if session.requested_fields:
                    raise InvalidInstitutionToken('identity_consent_required')
                subject = ObligationSubject.objects.select_for_update().get(pk=session.subject_id)
                if subject.confio_user_id not in (None, info.context.user.id):
                    raise InvalidInstitutionToken('membership_already_claimed')
                subject.confio_user = info.context.user
                subject.save(update_fields=('confio_user', 'updated_at'))
                session.status = 'authorized'
                session.authorized_at = timezone.now()
                session.save(update_fields=('status', 'authorized_at', 'updated_at'))
            return cls(success=True, errors=[])
        except InvalidInstitutionToken as exc:
            return cls(success=False, errors=[str(exc)])


class Mutation(graphene.ObjectType):
    create_member_payment_intent = CreateMemberPaymentIntent.Field()
    claim_institution_membership = ClaimInstitutionMembership.Field()
