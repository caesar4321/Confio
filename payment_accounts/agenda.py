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


def _label(value: str, fallback: str) -> str:
    value = ' '.join(str(value or '').split())[:100]
    return value or fallback[:100]


# ------------------------------------------------------------------ whose account

def _digits(value) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def _tokens(value) -> set[str]:
    import unicodedata
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().upper()
    return {token for token in ''.join(ch if ch.isalnum() else ' ' for ch in text).split() if len(token) > 1}


def _documents(account):
    """The verified personal documents of the account's owner (none for a
    business: its accounts are never "own" by a person's documents)."""
    if getattr(account, 'account_type', '') != 'personal' or not account.user_id:
        return []
    from security.identity_status import current_documents
    return [d for d in current_documents(account.user) if (d.risk_factors or {}).get('provider') == 'didit']


# Venezuelan identity cards (V nationals, E foreign residents), never a passport.
CEDULA_TYPES = ('national_id', 'foreign_id')


def _ve_cedulas(account):
    return [d for d in _documents(account)
            if str(d.document_issuing_country or '').upper() == 'VEN' and d.document_type in CEDULA_TYPES
            and _digits(d.document_number)]


def own_ve_cedula(account) -> str:
    """The person's verified Venezuelan cédula, normalized, or ''."""
    from ramps import ve_pagomovil
    for document in _ve_cedulas(account):
        number = str(document.document_number or '').strip().upper()
        if document.document_type == 'foreign_id' and number[:1].isdigit():
            number = f'E{number}'  # a foreign resident's cédula
        try:
            return ve_pagomovil.normalize_cedula(number)
        except ve_pagomovil.VePagoMovilError:
            continue
    return ''


def _is_own_cedula(account, cedula: str) -> bool:
    """Same digits as a verified Venezuelan document (the V/E prefix is how
    a bank writes it, not part of the identity)."""
    digits = _digits(cedula)
    return bool(digits) and any(_digits(d.document_number) == digits for d in _ve_cedulas(account))


def _holder_is_owner(account, holder_name: str, holder_document: str) -> bool:
    """A checked holder is the person when the rail's document ends like a
    verified document of theirs, or the holder carries their first and last name."""
    last4 = _digits(holder_document)[-4:]
    holder = _tokens(holder_name)
    for document in _documents(account):
        if last4 and len(last4) == 4 and _digits(document.document_number).endswith(last4):
            return True
        first = sorted(_tokens(document.verified_first_name))
        last = sorted(_tokens(document.verified_last_name))
        if first and last and holder and any(t in holder for t in first) and any(t in holder for t in last):
            return True
    return False


def _relationship_now(account, entry) -> str:
    """Whose an entry is, from verified data as it stands today."""
    if entry.rail == BANK_INFO:
        return AgendaEntry.OWN
    if entry.rail == VE_PAGOMOVIL:
        return AgendaEntry.OWN if _is_own_cedula(account, (entry.details or {}).get('cedula')) else AgendaEntry.THIRD_PARTY
    destination = entry.payout_destination
    if destination is None or not destination.holder_name:
        return AgendaEntry.THIRD_PARTY
    validation = (destination.provider_data or {}).get('validation') or {}
    return (AgendaEntry.OWN if _holder_is_owner(account, destination.holder_name, validation.get('holder_document', ''))
            else AgendaEntry.THIRD_PARTY)


def sync_relationships(account) -> None:
    """Re-derive whose each entry is before it is shown: a key re-registered
    to someone else leaves "Mías", a check that later matches the person
    joins it, and nothing self-declared by an older build survives."""
    changed = {AgendaEntry.OWN: [], AgendaEntry.THIRD_PARTY: []}
    for entry in entries(account):
        now = _relationship_now(account, entry)
        if entry.relationship != now:
            changed[now].append(entry.pk)
    for relationship, pks in changed.items():
        if pks:
            AgendaEntry.objects.filter(pk__in=pks).update(relationship=relationship, updated_at=timezone.now())


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

def save_ve_pagomovil(account, *, entry_id=None, label, relationship=None, holder_name, cedula, phone,
                      bank_code) -> AgendaEntry:
    """Create or edit a Venezuelan Pago Móvil entry, validated like an order.

    Whose account it is is not declared: "own" means the cédula is the
    person's verified Venezuelan document. Asking for "own" without one, or
    with another cédula, is refused; anything else is someone else's."""
    from ramps import ve_pagomovil
    wants_own = (relationship or '').strip().lower() == AgendaEntry.OWN
    if wants_own:
        # The verified cédula; a typed one with the same digits keeps its
        # V/E prefix (how the person's bank writes it).
        verified = own_ve_cedula(account)
        typed = str(cedula or '').strip().upper()
        keeps_prefix = typed[:1] in ('V', 'E') and _digits(typed) == _digits(verified)
        cedula = typed if verified and keeps_prefix else verified
        if not cedula:
            raise AgendaError('Para guardar un Pago Móvil como tuyo necesitamos tu cédula venezolana verificada.')
    try:
        details = {
            'cedula': ve_pagomovil.normalize_cedula(cedula),
            'phone': ve_pagomovil.normalize_phone(phone),
            'bank_code': ve_pagomovil.normalize_bank(bank_code),
        }
    except ve_pagomovil.VePagoMovilError as exc:
        raise AgendaError(str(exc)) from exc
    relationship = AgendaEntry.OWN if _is_own_cedula(account, details['cedula']) else AgendaEntry.THIRD_PARTY
    holder = ' '.join(str(holder_name or '').split())[:255]
    if relationship == AgendaEntry.OWN:
        holder = ''
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

def save_destination(account, *, destination_id, label, relationship=None) -> AgendaEntry:
    """Save a recipient the local-money flow already validated. Whose it is
    comes from the holder check, never from the person's say-so (older app
    builds still send `relationship`; it is ignored)."""
    del relationship
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
    validation = (destination.provider_data or {}).get('validation') or {}
    relationship = (AgendaEntry.OWN if destination.holder_name and _holder_is_owner(
        account, destination.holder_name, validation.get('holder_document', '')) else AgendaEntry.THIRD_PARTY)
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


# ------------------------------------------------------------------ what can be added

def methods(account, identity) -> list[dict]:
    """Every account type the person can add, by country, provider-neutral.
    `allows_third_party` comes from the rail, so a rail that starts accepting
    someone else's account changes here, not in the app."""
    from ramps.models import RampPaymentMethod
    from .local_money import methods as local_methods
    rows = [{
        'id': VE_PAGOMOVIL, 'kind': VE_PAGOMOVIL, 'country': 'VE', 'title': 'Pago Móvil',
        'subtitle': 'Cédula, teléfono y banco', 'allows_third_party': True, 'status': 'live', 'reason': '',
        'payment_method_id': None,
    }]
    for row in local_methods(account, identity, 'send'):
        method = row['method']
        if method.id not in INFINIA_RAILS:
            continue
        rows.append({
            'id': method.id, 'kind': 'local', 'country': method.iso2, 'title': method.title,
            'subtitle': method.subtitle, 'allows_third_party': method.id in THIRD_PARTY_RAILS,
            'status': row['status'], 'reason': row['reason'], 'payment_method_id': None,
        })
    for method in RampPaymentMethod.objects.filter(is_active=True, supports_off_ramp=True).order_by(
            'country_code', 'display_order', 'display_name'):
        rows.append({
            'id': f'{BANK_INFO}:{method.pk}', 'kind': BANK_INFO, 'country': method.country_code.upper(),
            'title': method.display_name, 'subtitle': 'Para tus retiros',
            'allows_third_party': BANK_INFO in THIRD_PARTY_RAILS, 'status': 'live', 'reason': '',
            'payment_method_id': str(method.pk),
        })
    return rows


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
    """Rename an entry. Whose it is follows from verified data, so a
    `relationship` from older builds is ignored."""
    del relationship
    entry = owned_entry(account, entry_id)
    entry.label = _label(label, entry.label)
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
