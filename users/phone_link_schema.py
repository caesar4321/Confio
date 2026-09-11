import logging

import graphene

from .phone_linking import (
    PhoneLinkError, PhoneRelinkRequired, read_confirmation,
    link_verified_phone, claim_verified_phone_invites,
)

logger = logging.getLogger(__name__)


class PreviousPhoneAccount(graphene.ObjectType):
    email = graphene.String(required=True)
    username = graphene.String(required=True)


class PhoneRelinkConfirmation(graphene.ObjectType):
    token = graphene.String(required=True)
    accounts = graphene.List(graphene.NonNull(PreviousPhoneAccount), required=True)


def confirmation_result(required):
    return PhoneRelinkConfirmation(token=required.token, accounts=[
        PreviousPhoneAccount(**account) for account in required.accounts])


class ConfirmPhoneRelink(graphene.Mutation):
    class Arguments:
        token = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    retryable = graphene.Boolean(default_value=False)
    relink_confirmation = graphene.Field(PhoneRelinkConfirmation)

    @classmethod
    def mutate(cls, root, info, token):
        user = getattr(info.context, 'user', None)
        if not user or not user.is_authenticated:
            return cls(success=False, error='Authentication required')
        try:
            from sms_verification.models import SMSVerification
            from telegram_verification.models import TelegramVerification

            payload = read_confirmation(token, user)
            model = {'sms_verification': SMSVerification,
                     'telegram_verification': TelegramVerification}.get(payload.get('channel'))
            proof = model.objects.filter(pk=payload.get('verification_id'), user=user).first() if model else None
            if not proof:
                raise PhoneLinkError('Solicita un nuevo código de verificación.')
            phone_key = link_verified_phone(user, proof, payload['country_code'], confirmation_token=token)
            claim_verified_phone_invites(user, info, phone_key)
            return cls(success=True)
        except PhoneRelinkRequired as required:
            return cls(success=False, error=str(required), relink_confirmation=confirmation_result(required))
        except PhoneLinkError as error:
            return cls(success=False, error=str(error))
        except Exception:
            logger.exception('Phone relink confirmation failed')
            return cls(success=False, retryable=True, error='No se pudo confirmar el cambio. Intenta de nuevo.')
