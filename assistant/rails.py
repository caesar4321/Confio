"""How a person can top up from their country, one answer for the guide and
the prompt."""
from dataclasses import dataclass

from . import conf

LOCAL_TOPUP_COUNTRIES = {'AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE', 'VE'}
# Guardarian's /v1/countries with supported=false, read 2026-11-01.
GUARDARIAN_UNSUPPORTED = frozenset("""
    AD AF AG AI AL AO AQ AS AW AX BB BD BF BH BI BL BM BO BQ BR BS BV BW BY BZ CC CD CI CK CM CN CU CW CX DZ EG EH ER
    ET FK FO GF GG GI GL GP GS GU HM HT IL IM IN IO IQ IR JE JM JO KH KN KP KR KY LB LY MA MC MF MK ML MM MN MO MP MQ
    MS MU MW MY MZ NA NC NF NI NP NU PA PF PM PN PR PS PW QA RE RU SA SD SH SJ SN SO SS SX SY TC TF TK TT TW UG UM VA
    VE VG VI VU WF XK YE YT ZW
""".split())


@dataclass(frozen=True)
class TopupEntry:
    """Where a country starts a top-up. `pointer` is the row's id on Recibir: a
    live rail's method id (localMoneyMethods), not the receive_* "coming soon"
    probe. The app circles any row by id, so changing it here needs no build."""
    name: str = 'Recargar ahora'
    pointer: str = 'recharge_now'
    chip: str = 'Sí, ir a Recargar'
    pointer_text: str = 'Toca aquí para crear tu recarga.'


DEFAULT_TOPUP_ENTRY = TopupEntry()
TOPUP_ENTRIES = {
    'VE': TopupEntry(name='Pago Móvil', pointer='ve_pagomovil_receive', chip='Sí, ir a Pago Móvil',
                     pointer_text='Toca aquí para recargar con Pago Móvil.'),
}
# Bolivia moves to this one by itself once its partner is approved.
BOLIVIA_QR_ENTRY = TopupEntry(name='QR Bolivia', pointer='bo_qr_receive', chip='Sí, ir a QR Bolivia',
                              pointer_text='Toca aquí para recargar con QR Bolivia.')


# While Koywe's top-up is paused for a country (Recibir hides "Recargar ahora"
# there), the person's own local account is where a top-up starts. The pointer
# is that rail's row id on Recibir.
PAUSED_TOPUP_ENTRIES = {
    'CO': TopupEntry(name='Llave Bre-B', pointer='co_breb_receive', chip='Sí, ir a Bre-B',
                     pointer_text='Toca aquí para recargar con tu llave Bre-B.'),
}


def local_account_topup(country, viewer):
    """The local-account entry that stands in for a paused Koywe top-up, for
    this person, or None. Only where the row really is on their Recibir: the
    rail is usable by them (or one identity check away, which the guide asks
    for first). Any doubt is None, and the guide falls back as before."""
    entry = PAUSED_TOPUP_ENTRIES.get((country or '').upper())
    if entry is None or viewer is None or getattr(viewer, 'user', None) is None:
        return None
    try:
        from django.conf import settings
        from payment_accounts import local_money
        from payment_accounts.local_money_schema import _identity
        from ramps.koywe import on_ramp_paused
        if not on_ramp_paused(country) or viewer.account_type != 'personal' or viewer.is_employee:
            return None
        # Cobre's key, when on, replaces this row under another id (local_money_schema).
        if getattr(settings, 'COBRE_PAYMENT_ACCOUNTS_ENABLED', False):
            return None
        method = local_money.METHODS[entry.pointer]
        status = local_money.rail_status(viewer.account, _identity(viewer.account, required=False), method)[0]
        if status == 'needs_verification':
            # One identity check away only for someone the guide will send to
            # verify first. A person it already counts as verified, whose
            # document this rail does not read, would be walked to a row
            # that asks them to verify again.
            from security.identity_status import is_identity_verified
            return None if is_identity_verified(viewer.user) else entry
        return entry if status == 'live' else None
    except Exception:  # noqa: BLE001 - unknown is "no entry", never a guess
        import logging
        logging.getLogger(__name__).warning('Confio Assistant: local account top-up state unavailable', exc_info=True)
        return None


def topup_entry(country, user, request_meta, viewer=None):
    # Decided by the person's rail, not where they live: Recibir hides Recargar
    # ahora for anyone QR Bolivia replaces it for.
    from ramps.bolivia_qr import koywe_replaced
    if koywe_replaced(user, request_meta or {})['top_up']:
        return BOLIVIA_QR_ENTRY
    return (local_account_topup(country, viewer)
            or TOPUP_ENTRIES.get((country or '').upper(), DEFAULT_TOPUP_ENTRY))


def topup_route(country):
    """'local', 'international' (live), 'international_soon' (not on yet) or 'usdt'."""
    country = (country or '').upper()
    if country in LOCAL_TOPUP_COUNTRIES:
        return 'local'
    if not country or country in GUARDARIAN_UNSUPPORTED:
        return 'usdt'
    return 'international' if conf.get('ASSISTANT_INTERNATIONAL_TOPUP_ENABLED') else 'international_soon'
