"""JWT-scoped Agenda API (saved own and third-party accounts).

Its own operations, like local money: an older server fails only the Agenda
screen. Mis cuentas rows are still created, edited and deleted with the
BankInfo mutations; they appear here through the mirror.
"""
import graphene
from graphql import GraphQLError

from . import agenda
from .agenda import AgendaError
from .models import AgendaEntry, PayoutDestination
from .services import PaymentAccountError

PERMISSION = 'manage_bank_accounts'


def _owner(info, owner_only=False):
    from .schema import _active_account
    return _active_account(info, permission=PERMISSION, owner_only=owner_only)


def _error(exc):
    if isinstance(exc, AgendaError):
        return str(exc)
    from .schema import _public_error
    return _public_error(exc)


class AgendaEntryType(graphene.ObjectType):
    id = graphene.String(required=True)
    rail = graphene.String(required=True)
    country = graphene.String(required=True)
    relationship = graphene.String(required=True)
    label = graphene.String(required=True)
    holder_name = graphene.String(required=True)
    subtitle = graphene.String(required=True)
    is_default = graphene.Boolean(required=True)
    cedula = graphene.String()
    phone = graphene.String()
    bank_code = graphene.String()
    bank_info_id = graphene.String()
    destination_id = graphene.String()


class AgendaRecentType(graphene.ObjectType):
    destination_id = graphene.String(required=True)
    rail = graphene.String(required=True)
    country = graphene.String(required=True)
    label = graphene.String(required=True)
    holder_name = graphene.String(required=True)


class AgendaMethodType(graphene.ObjectType):
    id = graphene.String(required=True)
    kind = graphene.String(required=True)
    country = graphene.String(required=True)
    title = graphene.String(required=True)
    subtitle = graphene.String(required=True)
    allows_third_party = graphene.Boolean(required=True)
    status = graphene.String(required=True)
    reason = graphene.String(required=True)
    payment_method_id = graphene.String()


def _entry(row):
    return AgendaEntryType(**agenda.view(row))


class AgendaQuery(graphene.ObjectType):
    agenda_entries = graphene.List(graphene.NonNull(AgendaEntryType), required=True)
    agenda_recents = graphene.List(graphene.NonNull(AgendaRecentType), required=True)
    agenda_methods = graphene.List(graphene.NonNull(AgendaMethodType), required=True)

    def resolve_agenda_entries(self, info):
        try:
            return [_entry(row) for row in agenda.entries(_owner(info))]
        except (AgendaError, PaymentAccountError) as exc:
            raise GraphQLError(_error(exc))

    def resolve_agenda_methods(self, info):
        from .schema import _verified_identity
        try:
            owner = _owner(info)
            try:
                identity = _verified_identity(owner)
            except PaymentAccountError:
                identity = None
            return [AgendaMethodType(**row) for row in agenda.methods(owner, identity)]
        except (AgendaError, PaymentAccountError) as exc:
            raise GraphQLError(_error(exc))

    def resolve_agenda_recents(self, info):
        try:
            return [AgendaRecentType(**row) for row in agenda.recents(_owner(info))]
        except (AgendaError, PaymentAccountError) as exc:
            raise GraphQLError(_error(exc))


class _AgendaMutation(graphene.Mutation):
    class Meta:
        abstract = True

    success = graphene.Boolean(required=True)
    errors = graphene.List(graphene.String, required=True)
    entry = graphene.Field(AgendaEntryType)


class SaveVePagomovilAgendaEntry(_AgendaMutation):
    class Arguments:
        id = graphene.String()
        label = graphene.String()
        relationship = graphene.String(required=True)
        holder_name = graphene.String()
        cedula = graphene.String(required=True)
        phone = graphene.String(required=True)
        bank_code = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, relationship, cedula, phone, bank_code, id=None, label='', holder_name=''):
        try:
            row = agenda.save_ve_pagomovil(
                _owner(info), entry_id=id, label=label, relationship=relationship, holder_name=holder_name,
                cedula=cedula, phone=phone, bank_code=bank_code)
            return cls(success=True, errors=[], entry=_entry(row))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], entry=None)


class SaveDestinationToAgenda(_AgendaMutation):
    class Arguments:
        destination_id = graphene.String(required=True)
        label = graphene.String()
        relationship = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, destination_id, relationship, label=''):
        try:
            row = agenda.save_destination(_owner(info), destination_id=destination_id, label=label,
                                          relationship=relationship)
            return cls(success=True, errors=[], entry=_entry(row))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], entry=None)


class UpdateAgendaEntry(_AgendaMutation):
    class Arguments:
        id = graphene.String(required=True)
        label = graphene.String(required=True)
        relationship = graphene.String()

    @classmethod
    def mutate(cls, root, info, id, label, relationship=None):
        try:
            row = agenda.rename(_owner(info), id, label=label, relationship=relationship)
            return cls(success=True, errors=[], entry=_entry(row))
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], entry=None)


class DeleteAgendaEntry(_AgendaMutation):
    class Arguments:
        id = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, id):
        try:
            agenda.delete(_owner(info), id)
            return cls(success=True, errors=[], entry=None)
        except Exception as exc:
            return cls(success=False, errors=[_error(exc)], entry=None)


class AgendaMutation(graphene.ObjectType):
    save_ve_pagomovil_agenda_entry = SaveVePagomovilAgendaEntry.Field()
    save_destination_to_agenda = SaveDestinationToAgenda.Field()
    update_agenda_entry = UpdateAgendaEntry.Field()
    delete_agenda_entry = DeleteAgendaEntry.Field()
