import graphene
from . import breb_location


class BrebLocationChallenge(graphene.Mutation):
    class Arguments:
        platform = graphene.String(default_value='android')
        key_id = graphene.String(default_value='')
    success = graphene.Boolean(required=True)
    challenge = graphene.String()
    cloud_project_number = graphene.String()
    key_registered = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, platform='android', key_id=''):
        from .schema import _active_account, _public_error
        try:
            owner = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            from django.conf import settings
            challenge = breb_location.challenge(owner, info.context.META, platform)
            registered = False
            if platform == 'ios' and key_id and len(key_id) <= 44:
                from .models import BrebAppAttestKey
                registered = BrebAppAttestKey.objects.filter(key_id=key_id, user_id=owner.user_id, revoked=False).exists()
            return cls(success=True, challenge=challenge, key_registered=registered,
                       cloud_project_number=str(settings.BREB_PLAY_CLOUD_PROJECT_NUMBER))
        except Exception as exc:
            return cls(success=False, error=str(exc) if isinstance(exc, breb_location.LocationError) else _public_error(exc))


class ApplyCobreBreb(graphene.Mutation):
    class Arguments:
        challenge = graphene.String(required=True)
        location_json = graphene.String(required=True)
        integrity_token = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    value = graphene.String()
    valid_until = graphene.Float()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, challenge, location_json, integrity_token):
        from .schema import _active_account, _verified_identity, _public_error
        from .services import provision_payment_account, create_funding_instruction
        try:
            owner = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            identity = _verified_identity(owner)
            permit = breb_location.verify(owner, info.context.META, challenge, location_json, integrity_token)
            valid_until = breb_location.grant_pass(owner)
            _, account = provision_payment_account(
                confio_account=owner, provider='cobre', identity=identity,
                country='COL', asset='COP', ownership_structure='omnibus_subledger', location_permit=permit)
            if not account or account.status != 'active':
                return cls(success=False, error='Tu solicitud está en proceso. Vuelve a intentarlo más tarde.')
            instruction = create_funding_instruction(financial_account=account, kind='breb_key', location_permit=permit)
            return cls(success=True, value=instruction.display_value, valid_until=valid_until)
        except Exception as exc:
            return cls(success=False, error=str(exc) if isinstance(exc, breb_location.LocationError) else _public_error(exc))


class VerifyBrebLocation(graphene.Mutation):
    """Every Bre-B screen: the same bound location + integrity evidence as the
    application, renewing a short location pass the Bre-B operations require."""

    class Arguments:
        challenge = graphene.String(required=True)
        location_json = graphene.String(required=True)
        integrity_token = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    valid_until = graphene.Float()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, challenge, location_json, integrity_token):
        from .schema import _active_account, _public_error
        try:
            owner = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            breb_location.verify(owner, info.context.META, challenge, location_json, integrity_token)
            return cls(success=True, valid_until=breb_location.grant_pass(owner))
        except Exception as exc:
            return cls(success=False, error=str(exc) if isinstance(exc, breb_location.LocationError) else _public_error(exc))


class BrebLocationMutation(graphene.ObjectType):
    breb_location_challenge = BrebLocationChallenge.Field()
    apply_cobre_breb = ApplyCobreBreb.Field()
    verify_breb_location = VerifyBrebLocation.Field()
