import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from datetime import timedelta
import requests
from django.conf import settings
from .models import TelegramVerification
from users.country_codes import COUNTRY_CODES
import logging
import re
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from users.phone_utils import normalize_phone
from users.models import Account
from blockchain.invite_send_mutations import ClaimInviteForPhone
import time

logger = logging.getLogger(__name__)

def validate_country_code(iso_code: str) -> bool:
    """Validate if the given ISO code exists in our country codes list."""
    return any(country[2] == iso_code for country in COUNTRY_CODES)

def get_country_code(iso_code: str) -> str:
    """Get the numeric country code for a given ISO code."""
    for country in COUNTRY_CODES:
        if country[2] == iso_code:
            return country[1].replace('+', '')  # Remove the + prefix
    return ''

def format_phone_number(phone_number):
    """Format phone number to E.164 format."""
    # Remove any non-digit characters
    digits = re.sub(r'\D', '', phone_number)
    
    # If number is 7 digits, assume it's a US number and add country code
    if len(digits) == 7:
        return f"+1646{digits}"  # Adding US country code (1) and area code (646)
    # If number is 10 digits, assume it's a US number without country code
    elif len(digits) == 10:
        return f"+1{digits}"
    # If number starts with 1 and has 11 digits, it's already a US number
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    # For other cases, just add + prefix
    else:
        return f"+{digits}"

class TelegramVerificationType(DjangoObjectType):
    class Meta:
        model = TelegramVerification
        fields = ('id', 'phone_number', 'created_at', 'expires_at', 'is_verified', 'request_id')

class InitiateTelegramVerification(graphene.Mutation):
    class Arguments:
        phone_number = graphene.String(required=True)
        country_code = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone_number, country_code):
        print("=== MUTATION CALLED ===")
        logger.info('=== Starting Telegram Verification ===')
        logger.info('Phone number received: %s', phone_number)
        logger.info('Country code received: %s', country_code)
        
        # Validate country code
        if not validate_country_code(country_code):
            logger.error('Invalid country code: %s', country_code)
            return InitiateTelegramVerification(success=False, error="Invalid country code")
        
        # Get numeric country code for formatting
        numeric_code = get_country_code(country_code)
        if not numeric_code:
            logger.error('Could not find numeric code for ISO: %s', country_code)
            return InitiateTelegramVerification(success=False, error="Invalid country code")
        
        # Format phone number to E.164
        formatted_phone = f"+{numeric_code}{phone_number}"
        logger.info('Formatted phone number: %s', formatted_phone)
        
        logger.info('Request headers: %s', dict(getattr(info.context, 'headers', {})))
        user = getattr(info.context, 'user', None)
        logger.info('User: %s, Is authenticated: %s', user, getattr(user, 'is_authenticated', False))
        
        if not (user and getattr(user, 'is_authenticated', False)):
            logger.warning('User not authenticated')
            return InitiateTelegramVerification(success=False, error="Authentication required")

        # Check if user exists in database
        User = get_user_model()
        try:
            user = User.objects.get(id=info.context.user.id)
            logger.info('Found user in database: %s', user)
        except User.DoesNotExist:
            logger.error('User not found in database: id=%s', info.context.user.id)
            return InitiateTelegramVerification(success=False, error="User not found. Please log in again.")

        TELEGRAM_GATEWAY_TOKEN = settings.TELEGRAM_API_TOKEN
        logger.info('Telegram API Token available: %s', bool(TELEGRAM_GATEWAY_TOKEN))
        ttl = 600  # 10 minutes
        
        logger.info('Initiating Telegram verification for phone number: %s', formatted_phone)
        logger.info('Using Telegram Gateway Token: %s...', TELEGRAM_GATEWAY_TOKEN[:10] if TELEGRAM_GATEWAY_TOKEN else 'None')
        
        try:
            request_url = 'https://gatewayapi.telegram.org/sendVerificationMessage'
            request_headers = {'Authorization': f'Bearer {TELEGRAM_GATEWAY_TOKEN}'}
            request_data = {
                'phone_number': formatted_phone,
                'ttl': ttl,
                'code_length': 6  # Set code length to 6 digits
            }
            
            logger.info('Sending request to Telegram API:')
            logger.info('URL: %s', request_url)
            logger.info('Headers: %s', request_headers)
            logger.info('Data: %s', request_data)
            
            response = requests.post(
                request_url,
                headers=request_headers,
                json=request_data
            )
            
            logger.info('Telegram API Response Status Code: %s', response.status_code)
            logger.info('Telegram API Response Headers: %s', dict(response.headers))
            logger.info('Telegram API Response Body: %s', response.text)
            
            data = response.json()
            if not data.get('ok'):
                error_msg = data.get('error', 'Unknown error')
                logger.error('Telegram API error: %s', error_msg)
                return InitiateTelegramVerification(success=False, error=error_msg)
            
            request_id = data['result']['request_id']
            expires_at = timezone.now() + timedelta(seconds=ttl)
            
            logger.info('Creating TelegramVerification record:')
            logger.info('Request ID: %s', request_id)
            logger.info('Expires at: %s', expires_at)
            
            TelegramVerification.objects.create(
                user=user,
                phone_number=formatted_phone,
                request_id=request_id,
                expires_at=expires_at
            )
            
            logger.info('Telegram verification initiated successfully')
            return InitiateTelegramVerification(success=True, error=None)
            
        except Exception as e:
            logger.exception('Failed to send verification: %s', str(e))
            return InitiateTelegramVerification(success=False, error=f"Failed to send verification: {str(e)}")

class VerifyTelegramCode(graphene.Mutation):
    class Arguments:
        phone_number = graphene.String(required=True)
        country_code = graphene.String(required=True)
        code = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, phone_number, country_code, code):
        user = getattr(info.context, 'user', None)
        logger.info('User: %s, Is authenticated: %s', user, getattr(user, 'is_authenticated', False))
        if not (user and getattr(user, 'is_authenticated', False)):
            return VerifyTelegramCode(success=False, error="Authentication required")
        try:
            # Validate country code
            if not validate_country_code(country_code):
                return VerifyTelegramCode(success=False, error="Invalid country code")
            
            # Get numeric country code
            numeric_code = get_country_code(country_code)
            if not numeric_code:
                return VerifyTelegramCode(success=False, error="Invalid country code")
            
            # Format phone number to E.164
            formatted_phone = f"+{numeric_code}{phone_number}"
            
            # Get the most recent unverified verification record
            verification = TelegramVerification.objects.filter(
                user=info.context.user,
                phone_number=formatted_phone,
                is_verified=False,
                expires_at__gt=timezone.now()
            ).order_by('-created_at').first()
            
            if not verification:
                return VerifyTelegramCode(success=False, error="No active verification request found.")
            
            # Clean up old verification records
            TelegramVerification.objects.filter(
                user=info.context.user,
                phone_number=formatted_phone,
                is_verified=False
            ).exclude(id=verification.id).delete()
            
            TELEGRAM_GATEWAY_TOKEN = settings.TELEGRAM_API_TOKEN
            
            # Try up to 3 times with a small delay between attempts
            max_attempts = 3
            attempt = 0
            last_error = None
            
            logger.info('Starting verification process for code: %s', code)
            
            while attempt < max_attempts:
                if attempt > 0:
                    # Wait 1 second between attempts
                    time.sleep(1)
                
                response = requests.post(
                    'https://gatewayapi.telegram.org/checkVerificationStatus',
                    headers={'Authorization': f'Bearer {TELEGRAM_GATEWAY_TOKEN}'},
                    json={
                        'request_id': verification.request_id,
                        'code': code
                    }
                )
                
                logger.info('Telegram API Response Status Code: %s', response.status_code)
                logger.info('Telegram API Response Headers: %s', dict(response.headers))
                logger.info('Telegram API Response Body: %s', response.text)
                
                data = response.json()
                if not data.get('ok'):
                    error_msg = data.get('error', 'Unknown error')
                    logger.error('Telegram API error: %s', error_msg)
                    return VerifyTelegramCode(success=False, error=error_msg)
                
                # Check if the response has the expected structure
                if 'result' not in data:
                    logger.error('Invalid response structure: missing "result" field')
                    return VerifyTelegramCode(success=False, error="Invalid response from verification service")
                
                result = data['result']
                
                # First check delivery status
                if 'delivery_status' not in result:
                    logger.error('Invalid response structure: missing "delivery_status" field in result')
                    return VerifyTelegramCode(success=False, error="Invalid response from verification service")
                
                delivery_status = result['delivery_status']
                if 'status' not in delivery_status:
                    logger.error('Invalid response structure: missing "status" field in delivery_status')
                    return VerifyTelegramCode(success=False, error="Invalid response from verification service")
                
                # Check if message was delivered
                if delivery_status['status'] not in ['delivered', 'read']:
                    return VerifyTelegramCode(success=False, error=f"Message not delivered. Status: {delivery_status['status']}")
                
                # Now check verification status
                if 'verification_status' not in result:
                    attempt += 1
                    last_error = "Waiting for verification status..."
                    logger.info('Attempt %d: %s', attempt, last_error)
                    continue
                
                verification_status = result['verification_status']
                if 'status' not in verification_status:
                    logger.error('Invalid response structure: missing "status" field in verification_status')
                    return VerifyTelegramCode(success=False, error="Invalid response from verification service")
                
                status = verification_status['status']
                logger.info('Verification status received: %s', status)
                
                # Only return success if the code is explicitly valid
                if status == 'code_valid':
                    logger.info('Code verification successful')
                    # Before changing user phone, check for duplicates using canonical key
                    user = info.context.user
                    phone_key = normalize_phone(phone_number, country_code)
                    from users.models import User as UserModel
                    duplicate_exists = UserModel.objects.filter(
                        phone_key=phone_key,
                        deleted_at__isnull=True
                    ).exclude(id=user.id).exists()
                    if duplicate_exists:
                        logger.error('Phone already in use by another account: %s', phone_key)
                        return VerifyTelegramCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")

                    # Update user's phone number and country code
                    try:
                        user.phone_number = phone_number  # Store without country code
                        user.phone_country = country_code  # Store ISO country code
                        user.save()
                        # Mark verification consumed only after successful save
                        verification.is_verified = True
                        verification.save(update_fields=['is_verified'])

                        # Auto-claim any existing invitation for this phone (best-effort)
                        try:
                            res = None
                            acct = Account.objects.filter(user=user, account_type='personal', account_index=0, deleted_at__isnull=True).first()
                            recipient_addr = getattr(acct, 'algorand_address', None)
                            if recipient_addr:
                                # Resolve the latest PhoneInvite for this canonical phone and claim by invitation_id
                                try:
                                    from send.models import PhoneInvite
                                    pk = normalize_phone(phone_number, country_code)
                                    inv = PhoneInvite.objects.filter(
                                        phone_key=pk,
                                        status='pending',
                                        deleted_at__isnull=True
                                    ).order_by('-created_at').first()
                                    if inv:
                                        res = ClaimInviteForPhone.mutate(None, info, recipient_address=recipient_addr, invitation_id=inv.invitation_id)
                                    else:
                                        logger.info('Auto-claim skipped: no pending PhoneInvite found for phone_key=%s', pk)
                                except Exception:
                                    logger.info('Auto-claim skipped due to DB lookup failure; will not attempt fallback claim')
                                if res is not None:
                                    ok = getattr(res, 'success', False)
                                    err = getattr(res, 'error', None)
                                    logger.info('Auto-claim invite result: success=%s error=%s', ok, err)
                            else:
                                logger.info('Auto-claim skipped: no personal account address found')
                        except Exception as ce:
                            logger.exception('Auto-claim invite failed: %s', ce)

                        return VerifyTelegramCode(success=True, error=None)
                    except IntegrityError as e:
                        logger.exception('Phone save failed due to uniqueness: %s', e)
                        return VerifyTelegramCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")
                    except Exception as e:
                        logger.exception('Unexpected error saving phone: %s', e)
                        return VerifyTelegramCode(success=False, error="Ocurrió un error al guardar tu número. Inténtalo de nuevo.")
                elif status == 'code_invalid':
                    logger.info('Code verification failed: invalid code')
                    return VerifyTelegramCode(success=False, error="Invalid verification code")
                elif status == 'code_max_attempts_exceeded':
                    logger.info('Code verification failed: max attempts exceeded')
                    return VerifyTelegramCode(success=False, error="Maximum number of verification attempts exceeded")
                elif status == 'expired':
                    logger.info('Code verification failed: code expired')
                    return VerifyTelegramCode(success=False, error="Verification code has expired")
                else:
                    logger.error('Unknown verification status: %s', status)
                    return VerifyTelegramCode(success=False, error=f"Verification failed: unknown status '{status}'")
            
            # If we've exhausted all attempts and still no verification status
            logger.error('Verification failed after %d attempts: %s', max_attempts, last_error)
            return VerifyTelegramCode(success=False, error=f"Verification status not available after {max_attempts} attempts. {last_error}")
            
        except Exception as e:
            logger.exception('Verification failed: %s', str(e))
            return VerifyTelegramCode(success=False, error=f"Verification failed: {str(e)}")

class Mutation(graphene.ObjectType):
    initiate_telegram_verification = InitiateTelegramVerification.Field()
    verify_telegram_code = VerifyTelegramCode.Field() 
