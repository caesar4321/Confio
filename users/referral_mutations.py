"""
Unified referral system mutations
Handles both influencer and friend referrals
"""
import graphene
from graphql import GraphQLError
from django.db import transaction as db_transaction
from .models import User
from achievements.models import InfluencerReferral, UserAchievement, AchievementType
from .decorators import rate_limit, check_suspicious_activity
import re


class SetReferrer(graphene.Mutation):
    """
    Single mutation for setting referrer (influencer or friend)
    Can only be done once per user within 48 hours of signup
    """
    class Arguments:
        referrer_identifier = graphene.String(required=True)
        referral_type = graphene.String()  # 'influencer' or 'friend', auto-detected if not provided
    
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
            existing_referral = InfluencerReferral.objects.filter(referred_user=user).first()
            if existing_referral:
                return SetReferrer(
                    success=False,
                    error="Ya tienes un referidor registrado. Solo puedes ser referido una vez."
                )
            
            # Check if within 48 hours of signup
            from django.utils import timezone
            from datetime import timedelta
            
            if user.created_at < timezone.now() - timedelta(hours=48):
                return SetReferrer(
                    success=False,
                    error="El período para registrar un referidor ha expirado (48 horas)."
                )
            
            # Clean the identifier
            identifier = referrer_identifier.strip().lower()
            
            # Auto-detect type if not provided
            if not referral_type:
                # Check if it's a phone number pattern
                phone_pattern = re.compile(r'^\+?\d{10,15}$')
                if phone_pattern.match(identifier.replace(' ', '')):
                    referral_type = 'friend'
                # Check if it's an invite code pattern (6-8 alphanumeric)
                elif re.match(r'^[A-Z0-9]{6,8}$', identifier.upper()):
                    referral_type = 'friend'
                else:
                    # Assume username (TikTok or Confío)
                    referral_type = 'influencer'
            
            # Always remove @ if present for any username type
            identifier = identifier.lstrip('@')
            
            # Find the referrer
            referrer = None
            referrer_username = identifier
            
            # Debug logging
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"SetReferrer: identifier='{identifier}', referral_type='{referral_type}'")
            
            if referral_type == 'friend':
                # Detect if it's a phone number
                if identifier.startswith('+') and len(identifier) >= 10:
                    # Phone number lookup
                    # Remove all non-digit characters except the leading +
                    clean_phone = '+' + ''.join(filter(str.isdigit, identifier))
                    
                    # Extract country code - try common LATAM lengths
                    country_code = None
                    phone_number = None
                    
                    # Try different country code lengths (2-4 digits)
                    for cc_length in [2, 3, 4]:
                        potential_cc = clean_phone[:cc_length+1]  # +1 for the + sign
                        potential_number = clean_phone[cc_length+1:]
                        
                        # Check if this country code exists in our system
                        if User.objects.filter(
                            phone_country=potential_cc,
                            phone_number=potential_number
                        ).exists():
                            country_code = potential_cc
                            phone_number = potential_number
                            break
                    
                    if country_code and phone_number:
                        referrer = User.objects.filter(
                            phone_country=country_code,
                            phone_number=phone_number
                        ).first()
                    else:
                        # Fallback: try to match just the phone number part (last 9-10 digits)
                        phone_digits = ''.join(filter(str.isdigit, identifier))
                        if len(phone_digits) >= 9:
                            referrer = User.objects.filter(
                                phone_number__endswith=phone_digits[-9:]
                            ).first()
                        else:
                            referrer = None
                    
                    if not referrer:
                        return SetReferrer(
                            success=False,
                            error=f"No se encontró ningún usuario con el número {clean_phone}. Verifica que el número sea correcto."
                        )
                else:
                    # Username lookup
                    # Validate username format (alphanumeric, underscore, 3-20 chars)
                    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', identifier):
                        return SetReferrer(
                            success=False,
                            error="Nombre de usuario inválido. Debe tener 3-20 caracteres alfanuméricos."
                        )
                    
                    referrer = User.objects.filter(username__iexact=identifier).first()
                    logger.info(f"Username lookup for '{identifier}': found={referrer is not None}")
                    if not referrer:
                        logger.warning(f"User not found with username: {identifier}")
                        return SetReferrer(
                            success=False,
                            error=f"No se encontró ningún usuario con el username @{identifier}"
                        )
                
                # Prevent self-referral
                if referrer.id == user.id:
                    return SetReferrer(
                        success=False,
                        error="No puedes ser tu propio referidor."
                    )
                
                referrer_username = referrer.username
            else:
                # Influencer (TikTok username)
                # Validate TikTok username format (letters, numbers, underscores, periods, 2-24 chars)
                if not re.match(r'^[a-zA-Z0-9_.]{2,24}$', identifier):
                    return SetReferrer(
                        success=False,
                        error="Username de TikTok inválido. Debe tener 2-24 caracteres (letras, números, _, .)"
                    )
                
                # For influencers, we don't validate if they exist in our system
                # They might not have a Confío account yet
                referrer_username = identifier
            
            # Create the referral record
            with db_transaction.atomic():
                referral = InfluencerReferral.objects.create(
                    referred_user=user,
                    referrer_identifier=referrer_username,
                    referral_type=referral_type,
                    influencer_user=referrer if referral_type == 'friend' else None,
                    status='pending',
                    attribution_data={
                        'referral_type': referral_type,
                        'identifier_used': identifier,
                        'registered_at': timezone.now().isoformat(),
                    }
                )
                
                # Note: Rewards will be given when first transaction is completed
                # This is handled by transaction signals
                
                message = (
                    f"¡Referidor registrado! Cuando completes tu primera transacción, "
                    f"ambos recibirán 4 CONFIO."
                )
                
                if referral_type == 'influencer':
                    message = (
                        f"¡Seguidor de @{referrer_username} registrado! "
                        f"Completa tu primera transacción para que ambos reciban 4 CONFIO."
                    )
                
                return SetReferrer(
                    success=True,
                    referral_type=referral_type,
                    message=message
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
    """Check if user can still set a referrer"""
    
    can_set_referrer = graphene.Boolean()
    time_remaining_hours = graphene.Int()
    existing_referrer = graphene.String()
    
    @classmethod
    def mutate(cls, root, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CheckReferralStatus(can_set_referrer=False)
        
        # Check existing referral
        existing = InfluencerReferral.objects.filter(referred_user=user).first()
        if existing:
            return CheckReferralStatus(
                can_set_referrer=False,
                existing_referrer=existing.referrer_identifier
            )
        
        # Check time limit
        from django.utils import timezone
        from datetime import timedelta
        
        signup_deadline = user.created_at + timedelta(hours=48)
        if timezone.now() > signup_deadline:
            return CheckReferralStatus(can_set_referrer=False, time_remaining_hours=0)
        
        time_remaining = signup_deadline - timezone.now()
        hours_remaining = int(time_remaining.total_seconds() / 3600)
        
        return CheckReferralStatus(
            can_set_referrer=True,
            time_remaining_hours=hours_remaining
        )