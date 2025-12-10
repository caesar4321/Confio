import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
from datetime import timedelta
import requests
from django.conf import settings
from django.core.cache import cache
from .models import TelegramVerification
from users.country_codes import COUNTRY_CODES
import logging
import re
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from users.phone_utils import normalize_phone
from users.models import Account
from blockchain.invite_send_mutations import ClaimInviteForPhone
from users.review_numbers import (
    get_review_test_code_for_phone,
    is_review_test_phone_key,
    find_matching_review_number,
)
import time
import uuid

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
            return InitiateTelegramVerification(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
        
        # Fuzzy match review number override
        review_override = find_matching_review_number(phone_number)
        if review_override:
            formatted_phone = review_override
        else:
            # Get numeric country code for formatting
            numeric_code = get_country_code(country_code)
            if not numeric_code:
                logger.error('Could not find numeric code for ISO: %s', country_code)
                return InitiateTelegramVerification(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
            
            # Format phone number to E.164
            formatted_phone = f"+{numeric_code}{phone_number}"
        logger.info('Formatted phone number: %s', formatted_phone)
        
        logger.info('Request headers: %s', dict(getattr(info.context, 'headers', {})))
        user = getattr(info.context, 'user', None)
        logger.info('User: %s, Is authenticated: %s', user, getattr(user, 'is_authenticated', False))
        
        if not (user and getattr(user, 'is_authenticated', False)):
            logger.warning('User not authenticated')
            return InitiateTelegramVerification(success=False, error="Por favor inicia sesión para verificar tu número de teléfono.")

        # Check if user exists in database
        User = get_user_model()
        try:
            user = User.objects.get(id=info.context.user.id)
            logger.info('Found user in database: %s', user)
        except User.DoesNotExist:
            logger.error('User not found in database: id=%s', info.context.user.id)
            return InitiateTelegramVerification(success=False, error="Sesión expirada. Por favor inicia sesión nuevamente.")

        TELEGRAM_GATEWAY_TOKEN = settings.TELEGRAM_API_TOKEN
        logger.info('Telegram API Token available: %s', bool(TELEGRAM_GATEWAY_TOKEN))
        ttl = 600  # 10 minutes
        
        logger.info('Initiating Telegram verification for phone number: %s', formatted_phone)
        logger.info('Using Telegram Gateway Token: %s...', TELEGRAM_GATEWAY_TOKEN[:10] if TELEGRAM_GATEWAY_TOKEN else 'None')

        # Reviewer bypass: create a local verification record without calling Telegram API
        review_code = get_review_test_code_for_phone(formatted_phone)
        if review_code:
            logger.info('Review test phone detected; skipping Telegram API call')
            # Clean up prior pending verifications for this phone
            TelegramVerification.objects.filter(
                user=user,
                phone_number=formatted_phone,
                is_verified=False,
                expires_at__gt=timezone.now()
            ).delete()
            request_id = f"review-{uuid.uuid4()}"
            TelegramVerification.objects.create(
                user=user,
                phone_number=formatted_phone,
                request_id=request_id,
                expires_at=timezone.now() + timedelta(seconds=ttl)
            )
            logger.info('Stored local Telegram verification request for review testing (request_id=%s)', request_id)
            return InitiateTelegramVerification(success=True, error=None)
        
        # Rate limiting: Check if user has made a request recently or is in flood wait
        rate_limit_key = f"telegram_verification_rate_limit:{user.id}:{formatted_phone}"
        flood_limit_key = f"telegram_flood_wait:{user.id}:{formatted_phone}"
        
        # Check for flood wait first (higher priority)
        flood_wait_time = cache.get(flood_limit_key)
        if flood_wait_time:
            return InitiateTelegramVerification(
                success=False, 
                error="Se enviaron demasiadas solicitudes recientemente. Por favor inténtalo más tarde."
            )
        
        # Check normal rate limit
        last_request_time = cache.get(rate_limit_key)
        if last_request_time:
            time_since_last = time.time() - last_request_time
            min_interval = 60  # 60 seconds minimum between requests
            
            if time_since_last < min_interval:
                remaining_wait = int(min_interval - time_since_last)
                logger.warning(f'Rate limit exceeded for user {user.id}, phone {formatted_phone}. Wait {remaining_wait}s')
                return InitiateTelegramVerification(
                    success=False, 
                    error=f"Por favor espera {remaining_wait} segundos antes de solicitar otro código"
                )
        
        # Set rate limit cache entry (expires after 60 seconds)
        cache.set(rate_limit_key, time.time(), 60)
        
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
                
                # Handle FLOOD_WAIT errors specifically
                if error_msg.startswith('FLOOD_WAIT_'):
                    try:
                        wait_seconds = int(error_msg.split('_')[-1])
                        wait_minutes = wait_seconds // 60
                        if wait_minutes > 0:
                            friendly_msg = f"Demasiadas solicitudes. Por favor espera {wait_minutes} minutos antes de intentar nuevamente."
                        else:
                            friendly_msg = f"Demasiadas solicitudes. Por favor espera {wait_seconds} segundos antes de intentar nuevamente."
                        
                        # Also set a longer rate limit for this user due to flood wait
                        flood_limit_key = f"telegram_flood_wait:{user.id}:{formatted_phone}"
                        cache.set(flood_limit_key, time.time(), wait_seconds)
                        
                        return InitiateTelegramVerification(success=False, error=friendly_msg)
                    except (ValueError, IndexError):
                        return InitiateTelegramVerification(success=False, error="Demasiadas solicitudes. Por favor inténtalo más tarde.")
                
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
            return InitiateTelegramVerification(success=False, error="No se pudo enviar el código de verificación. Por favor verifica tu número de teléfono e inténtalo nuevamente.")

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
            return VerifyTelegramCode(success=False, error="Por favor inicia sesión para verificar tu código.")
        try:
            # Validate country code
            if not validate_country_code(country_code):
                return VerifyTelegramCode(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
            
            # Fuzzy match review number override
            review_override = find_matching_review_number(phone_number)
            if review_override:
                formatted_phone = review_override
            else:
                # Get numeric country code
                numeric_code = get_country_code(country_code)
                if not numeric_code:
                    return VerifyTelegramCode(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
                
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
                return VerifyTelegramCode(success=False, error="No se encontró una solicitud de verificación activa. Por favor solicita un nuevo código.")
            
            # Clean up old verification records
            TelegramVerification.objects.filter(
                user=info.context.user,
                phone_number=formatted_phone,
                is_verified=False
            ).exclude(id=verification.id).delete()

            def finalize_success():
                try:
                    user.phone_number = phone_number  # Store without country code
                    user.phone_country = country_code  # Store ISO country code
                    user.save()
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

            # Reviewer bypass: match configured static code without calling Telegram
            review_code = get_review_test_code_for_phone(formatted_phone)
            if review_code:
                logger.info('Review test phone detected during Telegram verification')
                if code != review_code:
                    return VerifyTelegramCode(success=False, error="Código de verificación inválido. Por favor verifica el código e inténtalo nuevamente.")
                phone_key = normalize_phone(phone_number, country_code)
                allow_duplicates = is_review_test_phone_key(phone_key)
                if not allow_duplicates:
                    from users.models import User as UserModel
                    duplicate_exists = UserModel.objects.filter(
                        phone_key=phone_key,
                        deleted_at__isnull=True
                    ).exclude(id=user.id).exists()
                    if duplicate_exists:
                        logger.error('Phone already in use by another account: %s', phone_key)
                        return VerifyTelegramCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")
                return finalize_success()
            
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
                    return VerifyTelegramCode(success=False, error=f"Error del servicio de verificación: {error_msg}")
                
                # Check if the response has the expected structure
                if 'result' not in data:
                    logger.error('Invalid response structure: missing "result" field')
                    return VerifyTelegramCode(success=False, error="Respuesta inválida del servicio de verificación. Por favor inténtalo nuevamente.")
                
                result = data['result']
                
                # First check delivery status
                if 'delivery_status' not in result:
                    logger.error('Invalid response structure: missing "delivery_status" field in result')
                    return VerifyTelegramCode(success=False, error="Respuesta inválida del servicio de verificación. Por favor inténtalo nuevamente.")
                
                delivery_status = result['delivery_status']
                if 'status' not in delivery_status:
                    logger.error('Invalid response structure: missing "status" field in delivery_status')
                    return VerifyTelegramCode(success=False, error="Respuesta inválida del servicio de verificación. Por favor inténtalo nuevamente.")
                
                # Check if message was delivered
                if delivery_status['status'] not in ['delivered', 'read']:
                    return VerifyTelegramCode(success=False, error=f"Mensaje no entregado. Estado: {delivery_status['status']}. Por favor verifica que tienes Telegram instalado.")
                
                # Now check verification status
                if 'verification_status' not in result:
                    attempt += 1
                    last_error = "Esperando estado de verificación..."
                    logger.info('Attempt %d: %s', attempt, last_error)
                    continue
                
                verification_status = result['verification_status']
                if 'status' not in verification_status:
                    logger.error('Invalid response structure: missing "status" field in verification_status')
                    return VerifyTelegramCode(success=False, error="Respuesta inválida del servicio de verificación. Por favor inténtalo nuevamente.")
                
                status = verification_status['status']
                logger.info('Verification status received: %s', status)
                
                # Only return success if the code is explicitly valid
                if status == 'code_valid':
                    logger.info('Code verification successful')
                    # Before changing user phone, check for duplicates using canonical key
                    user = info.context.user
                    phone_key = normalize_phone(phone_number, country_code)
                    allow_duplicates = is_review_test_phone_key(phone_key)
                    if not allow_duplicates:
                        from users.models import User as UserModel
                        duplicate_exists = UserModel.objects.filter(
                            phone_key=phone_key,
                            deleted_at__isnull=True
                        ).exclude(id=user.id).exists()
                        if duplicate_exists:
                            logger.error('Phone already in use by another account: %s', phone_key)
                            return VerifyTelegramCode(success=False, error="Este número ya está registrado en Confío. Inicia sesión o recupera tu cuenta.")

                    return finalize_success()
                elif status == 'code_invalid':
                    logger.info('Code verification failed: invalid code')
                    return VerifyTelegramCode(success=False, error="Código de verificación inválido. Por favor verifica el código e inténtalo nuevamente.")
                elif status == 'code_max_attempts_exceeded':
                    logger.info('Code verification failed: max attempts exceeded')
                    return VerifyTelegramCode(success=False, error="Excediste el número máximo de intentos de verificación. Por favor solicita un nuevo código.")
                elif status == 'expired':
                    logger.info('Code verification failed: code expired')
                    return VerifyTelegramCode(success=False, error="El código de verificación ha expirado. Por favor solicita un nuevo código.")
                else:
                    logger.error('Unknown verification status: %s', status)
                    return VerifyTelegramCode(success=False, error=f"Verificación falló: estado desconocido '{status}'. Por favor inténtalo nuevamente.")
            
            # If we've exhausted all attempts and still no verification status
            logger.error('Verification failed after %d attempts: %s', max_attempts, last_error)
            return VerifyTelegramCode(success=False, error=f"Estado de verificación no disponible después de {max_attempts} intentos. {last_error}")
            
        except Exception as e:
            logger.exception('Verification failed: %s', str(e))
            return VerifyTelegramCode(success=False, error=f"Verificación falló: {str(e)}")

class CheckTelegramDeliveryStatus(graphene.Mutation):
    class Arguments:
        phone_number = graphene.String(required=True)
        country_code = graphene.String(required=True)
        
    success = graphene.Boolean()
    delivery_status = graphene.String()
    error = graphene.String()
    can_retry = graphene.Boolean()
    
    @classmethod
    def mutate(cls, root, info, phone_number, country_code):
        user = getattr(info.context, 'user', None)
        logger.info('CheckTelegramDeliveryStatus called for user: %s', user)
        
        if not (user and getattr(user, 'is_authenticated', False)):
            return CheckTelegramDeliveryStatus(success=False, error="Autenticación requerida. Por favor inicia sesión.")
            
        # Validate country code
        if not validate_country_code(country_code):
            return CheckTelegramDeliveryStatus(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
        
        # Fuzzy match review number override
        review_override = find_matching_review_number(phone_number)
        if review_override:
            formatted_phone = review_override
        else:
            # Get numeric country code for formatting
            numeric_code = get_country_code(country_code)
            if not numeric_code:
                return CheckTelegramDeliveryStatus(success=False, error="Código de país inválido. Por favor selecciona un país válido.")
            
            # Format phone number to E.164
            formatted_phone = f"+{numeric_code}{phone_number}"
        
        try:
            # Find the most recent verification request for this user and phone
            verification = TelegramVerification.objects.filter(
                user=user,
                phone_number=formatted_phone,
                deleted_at__isnull=True
            ).order_by('-created_at').first()
            
            if not verification:
                return CheckTelegramDeliveryStatus(
                    success=False, 
                    error="No se encontró solicitud de verificación. Por favor inicia el proceso de verificación.", 
                    can_retry=True
                )
            
            # Check if verification has expired
            if timezone.now() > verification.expires_at:
                return CheckTelegramDeliveryStatus(
                    success=True, 
                    delivery_status="expired", 
                    error="La verificación ha expirado. Por favor solicita un nuevo código.", 
                    can_retry=True
                )
            
            # Query Telegram API for delivery status
            TELEGRAM_GATEWAY_TOKEN = settings.TELEGRAM_API_TOKEN
            request_url = f'https://gatewayapi.telegram.org/checkVerificationStatus?request_id={verification.request_id}'
            request_headers = {'Authorization': f'Bearer {TELEGRAM_GATEWAY_TOKEN}'}
            
            response = requests.get(request_url, headers=request_headers)
            logger.info('Telegram delivery check response: %s', response.text)
            
            if response.status_code != 200:
                return CheckTelegramDeliveryStatus(
                    success=False, 
                    error="Error al verificar el estado de entrega. Por favor inténtalo nuevamente.", 
                    can_retry=True
                )
            
            data = response.json()
            if not data.get('ok'):
                return CheckTelegramDeliveryStatus(
                    success=False, 
                    error=f"Error del servicio: {data.get('error', 'Error desconocido')}", 
                    can_retry=True
                )
            
            result = data.get('result', {})
            delivery_status = result.get('delivery_status', {})
            status = delivery_status.get('status', 'unknown')
            
            # Determine if user can retry based on status
            can_retry = status in ['failed', 'expired', 'unknown']
            
            return CheckTelegramDeliveryStatus(
                success=True,
                delivery_status=status,
                error=None,
                can_retry=can_retry
            )
            
        except Exception as e:
            logger.exception('Failed to check delivery status: %s', str(e))
            return CheckTelegramDeliveryStatus(
                success=False, 
                error=f"Error al verificar el estado de entrega: {str(e)}", 
                can_retry=True
            )

class Mutation(graphene.ObjectType):
    initiate_telegram_verification = InitiateTelegramVerification.Field()
    verify_telegram_code = VerifyTelegramCode.Field()
    check_telegram_delivery_status = CheckTelegramDeliveryStatus.Field() 
