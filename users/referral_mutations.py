"""Unified referral system mutations for Confío usernames or phone numbers."""
import logging
import graphene
from decimal import Decimal
from django.db import transaction as db_transaction
from .models import User, Account
from .phone_utils import normalize_any_phone
from achievements.models import UserReferral, UserAchievement, AchievementType
from .decorators import rate_limit, check_suspicious_activity
from .jwt_context import get_jwt_business_context_with_validation
from django.utils import timezone
import re

_logger = logging.getLogger(__name__)


class SetReferrer(graphene.Mutation):
    """Registers who invited the current user (username or phone)."""
    class Arguments:
        referrer_identifier = graphene.String(required=True)
        referral_type = graphene.String()  # kept for backward compatibility
    
    success = graphene.Boolean()
    error = graphene.String()
    referral_type = graphene.String()
    message = graphene.String()
    
    @classmethod
    @rate_limit('referral_submit')
    @check_suspicious_activity('referral_submit')
    def mutate(cls, root, info, referrer_identifier, referral_type=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SetReferrer(success=False, error="Authentication required")
        account_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if account_context and account_context.get('account_type') == 'business':
            return SetReferrer(
                success=False,
                error="Los bonos de referidos solo están disponibles para cuentas personales.",
            )
        if not _has_personal_account(user):
            return SetReferrer(
                success=False,
                error="Necesitas una cuenta personal para participar en el programa de referidos.",
            )
        
        try:
            # Check if user already has a referral
            existing_referral = UserReferral.objects.filter(referred_user=user, deleted_at__isnull=True).first()
            if existing_referral:
                return SetReferrer(
                    success=False,
                    error=f"Ya registraste a @{existing_referral.referrer_identifier}."
                )

            # Clean the identifier
            identifier = referrer_identifier.strip().lower()

            # Auto-detect type if not provided
            # Always remove @ if present and normalize spaces
            identifier = identifier.lstrip('@').strip()
            referral_type = 'friend'

            # Determine whether identifier is phone or username
            is_phone = re.fullmatch(r'^\+?\d{10,15}$', identifier.replace(' ', '')) is not None

            referrer_user = None
            referrer_identifier = identifier

            if is_phone:
                clean_phone = '+' + ''.join(filter(str.isdigit, identifier))
                normalized = normalize_any_phone(clean_phone)
                if not normalized:
                    return SetReferrer(
                        success=False,
                        error="Número de teléfono inválido."
                    )
                referrer_user = User.objects.filter(phone_key=normalized).first()
                if not referrer_user:
                    return SetReferrer(
                        success=False,
                        error=f"No se encontró ningún usuario con el número {clean_phone}."
                    )
                referrer_identifier = referrer_user.username or clean_phone
            else:
                if not re.match(r'^[a-zA-Z0-9_]{3,20}$', identifier):
                    return SetReferrer(
                        success=False,
                        error="Nombre de usuario inválido. Usa solo letras, números o guión bajo (3-20 caracteres)."
                    )
                referrer_user = User.objects.filter(username__iexact=identifier).first()
                if not referrer_user:
                    return SetReferrer(
                        success=False,
                        error=f"No se encontró ningún usuario con el username @{identifier}"
                    )
                referrer_identifier = referrer_user.username

            if referrer_user and referrer_user.id == user.id:
                return SetReferrer(success=False, error="No puedes ser tu propio referidor.")
            if referrer_user and not _has_personal_account(referrer_user):
                return SetReferrer(
                    success=False,
                    error="Los referidores deben usar una cuenta personal.",
                )

            # Calculate reward amounts based on current CONFIO price
            # Both referee and referrer get $5 USD worth of CONFIO each
            try:
                from blockchain.rewards_service import ConfioRewardsService
                service = ConfioRewardsService()
                reward_per_person_cusd = Decimal('5')  # $5 USD per person
                confio_per_person = service.convert_cusd_to_confio(reward_per_person_cusd)

                # Both get the same amount (e.g., 20 CONFIO at $0.25/CONFIO)
                referee_confio = confio_per_person.quantize(Decimal('0.01'))
                referrer_confio = confio_per_person.quantize(Decimal('0.01'))
            except Exception as e:
                # Fallback to default amounts if service unavailable
                referee_confio = Decimal('20')  # $5 at $0.25/CONFIO
                referrer_confio = Decimal('20')  # $5 at $0.25/CONFIO

            # Create the referral record
            with db_transaction.atomic():
                referral = UserReferral.objects.create(
                    referred_user=user,
                    referrer_identifier=referrer_identifier,
                    referrer_user=referrer_user,
                    status='pending',
                    # Populate reward amounts based on current CONFIO price
                    # so users can see what they're working toward
                    reward_referee_confio=referee_confio,
                    reward_referrer_confio=referrer_confio,
                    attribution_data={
                        'referral_type': 'friend',
                        'identifier_used': referrer_identifier,
                        'registered_at': timezone.now().isoformat(),
                    }
                )

                # Note: Rewards will be synced to on-chain vault when first qualifying event occurs
                # This is handled by sync_referral_reward_for_event() via signals
                
                return SetReferrer(
                    success=True,
                    referral_type='friend',
                    message="¡Referidor registrado! Completa tu primera operación válida y ambos recibirán el equivalente a US$5 en $CONFIO."
                )
                
        except Exception:
            # Ensure we always have a valid logger reference even if module state is odd
            _logger.exception("Error setting referrer", exc_info=True)
            return SetReferrer(
                success=False,
                error="Error al registrar referidor. Por favor intenta de nuevo."
            )


class CheckReferralStatus(graphene.Mutation):
    """Returns the registered referrer, if any."""
    
    can_set_referrer = graphene.Boolean()
    existing_referrer = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CheckReferralStatus(can_set_referrer=False)
        
        existing = UserReferral.objects.filter(referred_user=user, deleted_at__isnull=True).first()
        if existing:
            return CheckReferralStatus(
                can_set_referrer=False,
                existing_referrer=existing.referrer_identifier
            )
        return CheckReferralStatus(can_set_referrer=True)
def _has_personal_account(user: User) -> bool:
    return Account.objects.filter(
        user=user, account_type='personal', deleted_at__isnull=True
    ).exists()
