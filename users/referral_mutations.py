"""Unified referral system mutations for Confío usernames or phone numbers."""
import graphene
from django.db import transaction as db_transaction
from .models import User
from .phone_utils import normalize_any_phone
from achievements.models import UserReferral, UserAchievement, AchievementType
from .decorators import rate_limit, check_suspicious_activity
from django.utils import timezone
import re


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

            # Create the referral record
            with db_transaction.atomic():
                referral = UserReferral.objects.create(
                    referred_user=user,
                    referrer_identifier=referrer_identifier,
                    referrer_user=referrer_user,
                    status='pending',
                    attribution_data={
                        'referral_type': 'friend',
                        'identifier_used': referrer_identifier,
                        'registered_at': timezone.now().isoformat(),
                    }
                )
                
                # Note: Rewards will be given when first transaction is completed
                # This is handled by transaction signals
                
                return SetReferrer(
                    success=True,
                    referral_type='friend',
                    message="¡Referidor registrado! Completa tu primera operación válida y ambos recibirán el equivalente a US$5 en $CONFIO."
                )
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error setting referrer: {str(e)}")
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
