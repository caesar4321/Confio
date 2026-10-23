"""Comprar's delivery address book.

Saved addresses belong to the user AND the JWT account they buy from (the
same account context as checkout), so employees of one business never see
each other's addresses. The Recarga (KYC) address is offered live and
read-only: it is the address the on-ramp provider holds, so Comprar never
edits or copies it; picking it only fills the delivery fields.
"""

import graphene
from django.db import transaction
from django.utils import timezone
from graphql_jwt.decorators import login_required

from users.models import Account

from .checkout import CheckoutError, jwt_account
from .models import DeliveryAddress
from .permissions import BUY

RECARGA_ID = 'recarga'


class DeliveryAddressType(graphene.ObjectType):
    id = graphene.ID()
    label = graphene.String()
    country_code = graphene.String()
    city = graphene.String()
    address = graphene.String()
    phone = graphene.String()
    note = graphene.String()
    is_default = graphene.Boolean()
    source = graphene.String(description='"saved" (the book) or "recarga" (the Recarga address, read-only)')
    editable = graphene.Boolean()


def _context(info):
    """(user, account) for the JWT account, with the permission to buy."""
    from .schema import _jwt, _user

    user = _user(info)
    if not user:
        raise CheckoutError('not_authenticated')
    ctx = _jwt(info, BUY)
    if ctx is None:
        raise CheckoutError('permission_denied')
    return user, jwt_account(user, ctx)


def _book(user, account):
    return DeliveryAddress.objects.filter(user=user, account=account, deleted_at__isnull=True)


def _phone_digits(phone: str) -> str:
    return ''.join(ch for ch in (phone or '') if ch.isdigit())


def _same_place(address: str, city: str, phone: str, country: str):
    """What makes two entries the same address (spacing and case aside)."""
    return (' '.join((address or '').lower().split()), (city or '').strip().lower(), _phone_digits(phone),
            (country or '').strip().upper())


def _saved(a: DeliveryAddress) -> DeliveryAddressType:
    return DeliveryAddressType(
        id=str(a.pk), label=a.label, country_code=a.country_code, city=a.city, address=a.address,
        phone=a.phone, note=a.note, is_default=a.is_default, source='saved', editable=True)


def _user_phone(user) -> str:
    """The verified phone as +<calling code><digits> (phone_key is "cc:digits")."""
    key = getattr(user, 'phone_key', None) or ''
    if ':' in key:
        cc, digits = key.split(':', 1)
        if cc.isdigit() and digits.isdigit():
            return f'+{cc}{digits}'
    return ''


def recarga_address(user) -> DeliveryAddressType | None:
    """The Recarga address as a book entry, or None when there is none usable."""
    from ramps.models import RampUserAddress

    ramp = RampUserAddress.objects.filter(user=user).first()
    street = (getattr(ramp, 'address_street', '') or '').strip()
    city = (getattr(ramp, 'address_city', '') or '').strip()
    country = (getattr(user, 'phone_country', '') or '').strip().upper()
    if not (street and city and country):
        return None
    neighborhood = (ramp.address_neighborhood or '').strip()
    address = street if not neighborhood or neighborhood.lower() in street.lower() else f'{street}, {neighborhood}'
    return DeliveryAddressType(
        id=RECARGA_ID, label='Mi dirección de Recarga', country_code=country, city=city,
        address=address[:300], phone=_user_phone(user), note='', is_default=False,
        source='recarga', editable=False)


def resolve_my_delivery_addresses(info):
    try:
        user, account = _context(info)
    except CheckoutError:
        return []
    saved = [_saved(a) for a in _book(user, account)[:DeliveryAddress.MAX_PER_BOOK]]
    # The Recarga address and verified phone are the PERSON's KYC data: only
    # in their personal account. In a business account they would end up on
    # an order every authorized employee of that business can read.
    recarga = recarga_address(user) if account.account_type == 'personal' else None
    # Once saved (picked and used), the Recarga address is a book entry like
    # any other; offering it twice would only be noise.
    if recarga and not any(_same_place(s.address, s.city, s.phone, s.country_code)
                           == _same_place(recarga.address, recarga.city, recarga.phone, recarga.country_code)
                           for s in saved):
        saved.append(recarga)
    return saved


def _clean(label, country_code, city, address, phone, note):
    """The fields as stored, or a CheckoutError code. Exactly checkout's rules
    (checkout.prepare_order) and the order's field sizes: anything checkout
    accepts, the book accepts and stores the same way."""
    address = (address or '').strip()
    phone = ''.join(ch for ch in (phone or '') if ch.isdigit() or ch == '+')
    city = (city or '').strip()
    country_code = (country_code or '').strip().upper()
    if len(address) < 8:
        raise CheckoutError('delivery_address_required')
    if len(phone) < 7:
        raise CheckoutError('delivery_phone_required')
    if not (2 <= len(city) <= 100):
        raise CheckoutError('bad_city')
    if len(country_code) != 2 or not country_code.isalpha():
        raise CheckoutError('bad_country')
    return {
        'label': (label or '').strip()[:40], 'country_code': country_code, 'city': city[:100],
        'address': address[:300], 'phone': phone[:20], 'note': (note or '').strip()[:300],
    }


class SaveDeliveryAddress(graphene.Mutation):
    """Add or edit a book entry. Saving an address the book already has (same
    address, city and phone) updates that entry instead of duplicating it;
    `mark_used` records a purchase to it (the book lists recent ones first)."""

    class Arguments:
        address_id = graphene.ID(description='Edit this entry; omit to add (or match an existing one)')
        label = graphene.String()
        country_code = graphene.String(required=True)
        city = graphene.String(required=True)
        address = graphene.String(required=True)
        phone = graphene.String(required=True)
        note = graphene.String()
        make_default = graphene.Boolean()
        mark_used = graphene.Boolean()

    success = graphene.Boolean()
    error = graphene.String()
    address = graphene.Field(DeliveryAddressType)

    @login_required
    def mutate(self, info, country_code, city, address, phone, address_id=None, label='', note='',
               make_default=False, mark_used=False):
        try:
            user, account = _context(info)
            fields = _clean(label, country_code, city, address, phone, note)
        except CheckoutError as exc:
            return SaveDeliveryAddress(success=False, error=exc.code)
        with transaction.atomic():
            # One book at a time: locking its account row (not the entries,
            # which an empty book does not have) serializes saves and deletes,
            # so two at once cannot both pass the cap, add the same address or
            # leave two defaults.
            Account.objects.select_for_update().filter(pk=account.pk).first()
            book = list(_book(user, account))
            if address_id:
                if address_id == RECARGA_ID:
                    return SaveDeliveryAddress(success=False, error='address_not_editable')
                entry = next((a for a in book if str(a.pk) == str(address_id)), None)
                if entry is None:
                    return SaveDeliveryAddress(success=False, error='address_not_found')
            else:
                key = _same_place(fields['address'], fields['city'], fields['phone'], fields['country_code'])
                entry = next((a for a in book if _same_place(a.address, a.city, a.phone, a.country_code) == key), None)
                if entry is None and len(book) >= DeliveryAddress.MAX_PER_BOOK:
                    return SaveDeliveryAddress(success=False, error='address_book_full')
                if entry is not None and not fields['label']:
                    fields['label'] = entry.label  # re-saving from checkout keeps its name
            if entry is None:
                entry = DeliveryAddress(user=user, account=account)
            for name, value in fields.items():
                setattr(entry, name, value)
            if mark_used:
                entry.last_used_at = timezone.now()
            # The first address is the default; later ones only when asked.
            becomes_default = make_default or not any(a.is_default for a in book if a.pk != entry.pk)
            if becomes_default:
                DeliveryAddress.objects.filter(pk__in=[a.pk for a in book if a.pk != entry.pk and a.is_default]) \
                    .update(is_default=False)
                entry.is_default = True
            entry.save()
        return SaveDeliveryAddress(success=True, address=_saved(entry))


class DeleteDeliveryAddress(graphene.Mutation):
    class Arguments:
        address_id = graphene.ID(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    @login_required
    def mutate(self, info, address_id):
        try:
            user, account = _context(info)
        except CheckoutError as exc:
            return DeleteDeliveryAddress(success=False, error=exc.code)
        if address_id == RECARGA_ID:
            return DeleteDeliveryAddress(success=False, error='address_not_editable')
        try:
            pk = int(str(address_id))
        except (TypeError, ValueError):
            return DeleteDeliveryAddress(success=False, error='address_not_found')
        with transaction.atomic():
            Account.objects.select_for_update().filter(pk=account.pk).first()  # same book lock as saving
            entry = _book(user, account).filter(pk=pk).first()
            if entry is None:
                return DeleteDeliveryAddress(success=False, error='address_not_found')
            entry.deleted_at = timezone.now()
            was_default, entry.is_default = entry.is_default, False
            entry.save(update_fields=['deleted_at', 'is_default', 'updated_at'])
            if was_default:
                # The most recently used one takes over, so checkout keeps a preselection.
                heir = _book(user, account).first()
                if heir:
                    DeliveryAddress.objects.filter(pk=heir.pk).update(is_default=True)
        return DeleteDeliveryAddress(success=True)
