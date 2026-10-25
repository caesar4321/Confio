"""Agenda: the person's saved payment accounts, their own and other people's.

Provider-neutral (docs/plans/agenda-design.md). Each entry names a rail; the
rail decides its fields, its validation and whether someone else's account
may be saved:

  ve_pagomovil   Venezuelan Pago Móvil (cédula, mobile, SUDEBAN bank).
                 Own or third party. Agenda only.
  co_breb, mx_clabe, ar_cvu, br_pix
                 Infinia local sends. Own or third party. Saved by linking a
                 recipient already validated through the local-money flow
                 (a PayoutDestination); deleting the entry leaves the
                 recipient in the send screen's recents.
  bank_info      "Mis cuentas" (users.BankInfo, Koywe Retiro and P2P). Own
                 only. Written by the existing BankInfo mutations from every
                 app build; this module only mirrors those rows.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import AgendaEntry, PayoutDestination

VE_PAGOMOVIL = 've_pagomovil'
BANK_INFO = 'bank_info'
# Infinia methods that are an account (not a one-off merchant QR).
INFINIA_RAILS = ('co_breb', 'mx_clabe', 'ar_cvu', 'br_pix')
THIRD_PARTY_RAILS = (VE_PAGOMOVIL,) + INFINIA_RAILS


class AgendaError(Exception):
    """User-facing refusal (Spanish)."""


def _relationship(value: str, rail: str) -> str:
    value = (value or '').strip().lower()
    if value not in (AgendaEntry.OWN, AgendaEntry.THIRD_PARTY):
        raise AgendaError('Indica si la cuenta es tuya o de otra persona.')
    if value == AgendaEntry.THIRD_PARTY and rail not in THIRD_PARTY_RAILS:
        raise AgendaError('En este país solo puedes guardar cuentas a tu nombre.')
    return value


def _label(value: str, fallback: str) -> str:
    value = ' '.join(str(value or '').split())[:100]
    return value or fallback[:100]


def entries(account):
    return AgendaEntry.objects.filter(confio_account=account, deleted_at__isnull=True).select_related(
        'bank_info', 'payout_destination').order_by('-is_default', 'label')


def owned_entry(account, entry_id) -> AgendaEntry:
    from django.core.exceptions import ValidationError
    try:
        entry = entries(account).filter(internal_id=entry_id).first()
    except (ValueError, TypeError, ValidationError):
        entry = None
    if entry is None:
        raise AgendaError('No encontramos esa cuenta en tu Agenda.')
    return entry


# ------------------------------------------------------------------ VE Pago Móvil

def save_ve_pagomovil(account, *, entry_id=None, label, relationship, holder_name, cedula, phone,
                      bank_code) -> AgendaEntry:
    """Create or edit a Venezuelan Pago Móvil entry, validated like an order."""
    from ramps import ve_pagomovil
    try:
        details = {
            'cedula': ve_pagomovil.normalize_cedula(cedula),
            'phone': ve_pagomovil.normalize_phone(phone),
            'bank_code': ve_pagomovil.normalize_bank(bank_code),
        }
    except ve_pagomovil.VePagoMovilError as exc:
        raise AgendaError(str(exc)) from exc
    relationship = _relationship(relationship, VE_PAGOMOVIL)
    holder = ' '.join(str(holder_name or '').split())[:255]
    if relationship == AgendaEntry.THIRD_PARTY and not holder:
        raise AgendaError('Escribe el nombre de la persona.')
    fallback = f"{holder or 'Mi cuenta'} · {ve_pagomovil.BANK_NAMES[details['bank_code']]}"
    values = dict(rail=VE_PAGOMOVIL, country='VE', relationship=relationship, label=_label(label, fallback),
                  holder_name=holder, holder_id_type='cedula', holder_id_number=details['cedula'], details=details)
    with transaction.atomic():
        if entry_id:
            entry = owned_entry(account, entry_id)
            if entry.rail != VE_PAGOMOVIL:
                raise AgendaError('Esta cuenta se edita desde su propio formulario.')
            for key, value in values.items():
                setattr(entry, key, value)
            entry.save()
            return entry
        duplicate = entries(account).filter(rail=VE_PAGOMOVIL, details=details).first()
        if duplicate:
            return duplicate
        return AgendaEntry.objects.create(confio_account=account, **values)


# ------------------------------------------------------------------ Infinia recipients

def save_destination(account, *, destination_id, label, relationship) -> AgendaEntry:
    """Save a recipient the local-money flow already validated."""
    from .local_money import METHODS
    from django.core.exceptions import ValidationError
    try:
        destination = PayoutDestination.objects.filter(
            confio_account=account, provider='infinia', internal_id=destination_id).first()
    except (ValueError, TypeError, ValidationError):
        destination = None
    from .local_money import NOT_FOUND, verification_state
    method_id = ((destination.provider_data or {}).get('method_id') if destination else '') or ''
    if destination is None or method_id not in INFINIA_RAILS:
        raise AgendaError('No encontramos ese destinatario.')
    if verification_state((destination.provider_data or {}).get('validation')) == NOT_FOUND:
        raise AgendaError('Esa cuenta no existe. Revisa los datos.')
    relationship = _relationship(relationship, method_id)
    method = METHODS[method_id]
    with transaction.atomic():
        existing = AgendaEntry.objects.select_for_update().filter(payout_destination=destination).first()
        values = dict(rail=method_id, country=method.iso2, relationship=relationship,
                      label=_label(label, destination.holder_name or destination.label),
                      holder_name=destination.holder_name, holder_id_type=destination.holder_id_type,
                      holder_id_number=destination.holder_id_number,
                      details={'value': (destination.details or {}).get(method.field, '')},
                      confio_account=account, deleted_at=None)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.save()
            return existing
        return AgendaEntry.objects.create(payout_destination=destination, **values)


def recents(account, limit: int = 20) -> list[dict]:
    """Recent local-send recipients not in the Agenda yet ("Recientes")."""
    from .local_money import NOT_FOUND, verification_state
    rows = PayoutDestination.objects.filter(
        confio_account=account, provider='infinia', provider_data__method_id__in=INFINIA_RAILS,
    ).exclude(agenda_entry__isnull=False, agenda_entry__deleted_at__isnull=True).order_by('-created_at')[:limit * 2]
    result = []
    for row in rows:
        data = row.provider_data or {}
        if verification_state(data.get('validation')) == NOT_FOUND:
            continue
        result.append({'destination_id': str(row.internal_id), 'rail': data.get('method_id'),
                       'country': _iso2(data.get('method_id')),
                       'label': row.label, 'holder_name': row.holder_name})
        if len(result) >= limit:
            break
    return result


def _iso2(method_id) -> str:
    from .local_money import METHODS
    method = METHODS.get(method_id)
    return method.iso2 if method else ''


# ------------------------------------------------------------------ Mis cuentas mirror

def _bank_info_country(bank_info) -> str:
    method = bank_info.ramp_payment_method or bank_info.payment_method
    code = str(getattr(method, 'country_code', '') or '').upper()
    if not code and bank_info.country_id:
        code = str(getattr(bank_info.country, 'code', '') or '').upper()
    return code[:2]


def _bank_info_identifier(bank_info) -> str:
    return (bank_info.account_number or bank_info.phone_number or bank_info.email or bank_info.username or '').strip()


def mirror_bank_info(bank_info) -> None:
    """Keep the Agenda's copy of one Mis cuentas row (own account)."""
    method = bank_info.ramp_payment_method or bank_info.payment_method
    method_name = str(getattr(method, 'display_name', '') or 'Cuenta')
    identifier = _bank_info_identifier(bank_info)
    values = dict(
        confio_account_id=bank_info.account_id, rail=BANK_INFO, country=_bank_info_country(bank_info),
        relationship=AgendaEntry.OWN,
        label=_label('', f"{method_name} ···{identifier[-4:]}" if identifier else method_name),
        holder_name=(bank_info.account_holder_name or '')[:255],
        holder_id_type='', holder_id_number=(bank_info.identification_number or '')[:100],
        details={'method': method_name, 'identifier_last4': identifier[-4:]},
        is_default=bool(bank_info.is_default),
        deleted_at=bank_info.deleted_at,
    )
    entry, created = AgendaEntry.objects.get_or_create(bank_info=bank_info, defaults=values)
    if not created:
        AgendaEntry.objects.filter(pk=entry.pk).update(updated_at=timezone.now(), **values)
    if bank_info.is_default:
        # BankInfo clears the old default with a queryset update (no signal).
        AgendaEntry.objects.filter(confio_account_id=bank_info.account_id, rail=BANK_INFO, is_default=True).exclude(
            pk=entry.pk).update(is_default=False, updated_at=timezone.now())


@receiver(post_save, sender='users.BankInfo', dispatch_uid='agenda_mirror_bank_info')
def _bank_info_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        mirror_bank_info(instance)


# ------------------------------------------------------------------ edits

def rename(account, entry_id, *, label, relationship=None) -> AgendaEntry:
    entry = owned_entry(account, entry_id)
    entry.label = _label(label, entry.label)
    if relationship and entry.rail != BANK_INFO:
        entry.relationship = _relationship(relationship, entry.rail)
    entry.save()
    return entry


def delete(account, entry_id) -> None:
    entry = owned_entry(account, entry_id)
    if entry.rail == BANK_INFO:
        # Mis cuentas rows are removed with deleteBankInfo (their own flow),
        # which the mirror follows.
        raise AgendaError('Elimina esta cuenta desde Mis cuentas.')
    entry.deleted_at = timezone.now()
    entry.save(update_fields=['deleted_at', 'updated_at'])


def view(entry: AgendaEntry) -> dict:
    from ramps import ve_pagomovil
    details = entry.details or {}
    if entry.rail == VE_PAGOMOVIL:
        subtitle = f"{ve_pagomovil.BANK_NAMES.get(details.get('bank_code'), '')} · {details.get('phone', '')}"
    elif entry.rail == BANK_INFO:
        subtitle = f"{details.get('method', '')} ···{details.get('identifier_last4', '')}".strip()
    else:
        value = str(details.get('value') or '')
        subtitle = f"···{value[-4:]}" if len(value) > 4 else value
    return {
        'id': str(entry.internal_id), 'rail': entry.rail, 'country': entry.country,
        # A recipient's holder is read from its destination: a re-check that
        # finds the key moved to someone else clears it there.
        'relationship': entry.relationship, 'label': entry.label,
        'holder_name': entry.payout_destination.holder_name if entry.payout_destination_id else entry.holder_name,
        'subtitle': subtitle, 'is_default': entry.is_default,
        'cedula': details.get('cedula') if entry.rail == VE_PAGOMOVIL else None,
        'phone': details.get('phone') if entry.rail == VE_PAGOMOVIL else None,
        'bank_code': details.get('bank_code') if entry.rail == VE_PAGOMOVIL else None,
        'bank_info_id': str(entry.bank_info_id) if entry.bank_info_id else None,
        'destination_id': str(entry.payout_destination.internal_id) if entry.payout_destination_id else None,
    }
