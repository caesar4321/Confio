"""
Security-related GraphQL schema
"""
import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from django.core.cache import cache
import logging

from .models import (
    IdentityVerification, UserDevice, DeviceFingerprint,
    UserSession, IPAddress, AMLCheck, SuspiciousActivity
)
from .utils import (
    calculate_device_fingerprint, check_kyc_required,
    perform_aml_check, create_suspicious_activity
)

logger = logging.getLogger(__name__)


class IdentityVerificationType(DjangoObjectType):
    class Meta:
        model = IdentityVerification
        fields = ('id', 'status', 'verified_at', 'verified_first_name', 
                 'verified_last_name', 'document_type', 'created_at')

    def resolve_verified_at(self, info):
        try:
            return self.verified_at or getattr(self, 'updated_at', None) or getattr(self, 'created_at', None)
        except Exception:
            return None


class UserDeviceType(DjangoObjectType):
    device_name = graphene.String()
    
    class Meta:
        model = UserDevice
        fields = ('id', 'device', 'is_trusted', 'first_used', 'last_used', 
                 'total_sessions', 'trusted_at')
    
    def resolve_device_name(self, info):
        """Generate a friendly device name from fingerprint details"""
        details = self.device.device_details
        browser = details.get('user_agent', '').split(' ')[0]
        os = 'Unknown OS'
        
        user_agent = details.get('user_agent', '')
        if 'Windows' in user_agent:
            os = 'Windows'
        elif 'Mac' in user_agent:
            os = 'macOS'
        elif 'Linux' in user_agent:
            os = 'Linux'
        elif 'Android' in user_agent:
            os = 'Android'
        elif 'iOS' in user_agent or 'iPhone' in user_agent:
            os = 'iOS'
        
        return f"{browser} on {os}"


class AMLCheckType(DjangoObjectType):
    class Meta:
        model = AMLCheck
        fields = ('id', 'risk_score', 'status', 'risk_factors', 
                 'actions_required', 'created_at')


class TrustDevice(graphene.Mutation):
    """Mark a device as trusted after verification"""
    class Arguments:
        verification_code = graphene.String(required=True)
        device_fingerprint = graphene.JSONString(required=True)
        trust_reason = graphene.String()
    
    success = graphene.Boolean()
    error = graphene.String()
    device = graphene.Field(UserDeviceType)
    
    @classmethod
    def mutate(cls, root, info, verification_code, device_fingerprint, trust_reason=None):
        user = info.context.user
        if not user.is_authenticated:
            return TrustDevice(success=False, error="Authentication required")
        
        try:
            # Verify the code (sent via email/SMS)
            cache_key = f"device_trust_code_{user.id}"
            stored_code = cache.get(cache_key)
            
            if not stored_code or stored_code != verification_code:
                # Track failed attempts
                failed_key = f"device_trust_failed_{user.id}"
                failed_count = cache.get(failed_key, 0) + 1
                cache.set(failed_key, failed_count, 3600)  # 1 hour
                
                if failed_count >= 5:
                    create_suspicious_activity(
                        user=user,
                        activity_type='excessive_device_trust_failures',
                        detection_data={
                            'failed_attempts': failed_count,
                            'device_fingerprint': device_fingerprint
                        },
                        severity=7
                    )
                
                return TrustDevice(success=False, error="Invalid verification code")
            
            # Calculate fingerprint hash
            fingerprint_hash = calculate_device_fingerprint(device_fingerprint)
            
            # Get or create device fingerprint
            device_obj, created = DeviceFingerprint.objects.get_or_create(
                fingerprint=fingerprint_hash,
                defaults={
                    'device_details': device_fingerprint,
                    'first_seen': timezone.now(),
                    'last_seen': timezone.now()
                }
            )
            
            # Get or create user device relationship
            user_device, created = UserDevice.objects.get_or_create(
                user=user,
                device=device_obj,
                defaults={
                    'first_used': timezone.now(),
                    'last_used': timezone.now()
                }
            )
            
            # Mark as trusted
            user_device.is_trusted = True
            user_device.trusted_at = timezone.now()
            user_device.save()
            
            # Clear the verification code
            cache.delete(cache_key)
            cache.delete(failed_key)
            
            return TrustDevice(
                success=True,
                device=user_device
            )
            
        except Exception as e:
            logger.error(f"Error trusting device: {str(e)}")
            return TrustDevice(success=False, error=str(e))


class RequestDeviceTrust(graphene.Mutation):
    """Request a verification code to trust a device"""
    class Arguments:
        device_fingerprint = graphene.JSONString(required=True)
        method = graphene.String(default_value="email")  # email or sms
    
    success = graphene.Boolean()
    error = graphene.String()
    message = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, device_fingerprint, method):
        user = info.context.user
        if not user.is_authenticated:
            return RequestDeviceTrust(success=False, error="Authentication required")
        
        try:
            # Rate limit check
            rate_limit_key = f"device_trust_request_{user.id}"
            if cache.get(rate_limit_key):
                return RequestDeviceTrust(
                    success=False, 
                    error="Please wait before requesting another code"
                )
            
            # Generate verification code
            import random
            code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            
            # Store code in cache
            cache_key = f"device_trust_code_{user.id}"
            cache.set(cache_key, code, 600)  # 10 minutes
            
            # Set rate limit
            cache.set(rate_limit_key, True, 60)  # 1 minute cooldown
            
            # Send code based on method
            if method == "sms" and user.phone_number:
                # TODO: Implement SMS sending
                logger.info(f"Would send SMS to {user.phone_number}: {code}")
                message = f"Code sent to {user.phone_country}{user.phone_number[-4:]}"
            else:
                # TODO: Implement email sending
                logger.info(f"Would send email to {user.email}: {code}")
                message = f"Code sent to {user.email}"
            
            return RequestDeviceTrust(
                success=True,
                message=message
            )
            
        except Exception as e:
            logger.error(f"Error requesting device trust: {str(e)}")
            return RequestDeviceTrust(success=False, error=str(e))


class CheckKYCStatus(graphene.Mutation):
    """Check KYC status for current user"""
    class Arguments:
        operation_type = graphene.String(required=True)
        amount = graphene.Decimal()
    
    kyc_required = graphene.Boolean()
    reason = graphene.String()
    verification_status = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, operation_type, amount=None):
        user = info.context.user
        if not user.is_authenticated:
            return CheckKYCStatus(
                kyc_required=True,
                reason="Authentication required",
                verification_status="none"
            )
        
        # Check KYC requirement
        required, reason = check_kyc_required(user, operation_type, amount)
        
        # Get current verification status
        try:
            verification = IdentityVerification.objects.filter(
                user=user
            ).order_by('-created_at').first()
            
            verification_status = verification.status if verification else "none"
        except:
            verification_status = "none"
        
        return CheckKYCStatus(
            kyc_required=required,
            reason=reason,
            verification_status=verification_status
        )


class SecurityQuery(graphene.ObjectType):
    my_devices = graphene.List(UserDeviceType)
    my_kyc_status = graphene.Field(IdentityVerificationType)
    my_personal_kyc_status = graphene.Field(IdentityVerificationType)
    my_personal_verified_kyc = graphene.Field(IdentityVerificationType)
    business_kyc_status = graphene.Field(IdentityVerificationType, business_id=graphene.ID(required=True))
    
    def resolve_my_devices(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        return UserDevice.objects.filter(
            user=user
        ).select_related('device').order_by('-last_used')
    
    def resolve_my_kyc_status(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return None
        
        return IdentityVerification.objects.filter(
            user=user
        ).order_by('-created_at').first()

    def resolve_my_personal_kyc_status(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return None
        # Exclude business-context verifications to reflect personal status only
        return IdentityVerification.objects.filter(
            user=user,
            risk_factors__account_type__isnull=True
        ).order_by('-created_at').first()

    def resolve_business_kyc_status(self, info, business_id):
        user = info.context.user
        if not user.is_authenticated:
            return None
        # Return latest verification for the specified business context
        return IdentityVerification.objects.filter(
            risk_factors__account_type='business',
            risk_factors__business_id=str(business_id)
        ).order_by('-created_at').first()

    def resolve_my_personal_verified_kyc(self, info):
        user = info.context.user
        if not user.is_authenticated:
            return None
        return IdentityVerification.objects.filter(
            user=user,
            status='verified',
            risk_factors__account_type__isnull=True
        ).order_by('-verified_at', '-updated_at', '-created_at').first()


class SecurityMutation(graphene.ObjectType):
    check_kyc_status = CheckKYCStatus.Field()


# Export for main schema
Query = SecurityQuery
Mutation = SecurityMutation
