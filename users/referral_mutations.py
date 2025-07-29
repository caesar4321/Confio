"""
Unified referral system mutations
Handles both influencer and friend referrals
"""
import graphene
from graphql import GraphQLError
from django.db import transaction as db_transaction
from .models import User, InfluencerReferral, UserAchievement, AchievementType
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
                    # Assume TikTok username (remove @ if present)
                    referral_type = 'influencer'
                    identifier = identifier.lstrip('@')
            
            # Find the referrer
            referrer = None
            referrer_username = identifier
            
            if referral_type == 'friend':
                # Try to find friend by phone or invite code
                # For MVP, we'll use username as invite code
                referrer = User.objects.filter(username=identifier).first()
                if not referrer:
                    # Try by phone if it looks like a phone number
                    if identifier.startswith('+') or identifier.isdigit():
                        phone_clean = identifier.replace('+', '').replace(' ', '')
                        referrer = User.objects.filter(phone_number=phone_clean).first()
                
                if not referrer:
                    return SetReferrer(
                        success=False,
                        error="No se encontró ningún usuario con ese código de invitación."
                    )
                
                referrer_username = referrer.username
            
            # Create the referral record
            with db_transaction.atomic():
                referral = InfluencerReferral.objects.create(
                    referred_user=user,
                    tiktok_username=referrer_username,
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
                existing_referrer=existing.tiktok_username
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