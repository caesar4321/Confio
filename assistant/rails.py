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


def topup_entry(country, user, request_meta):
    # Decided by the person's rail, not where they live: Recibir hides Recargar
    # ahora for anyone QR Bolivia replaces it for.
    from ramps.bolivia_qr import koywe_replaced
    if koywe_replaced(user, request_meta or {})['top_up']:
        return BOLIVIA_QR_ENTRY
    return TOPUP_ENTRIES.get((country or '').upper(), DEFAULT_TOPUP_ENTRY)


def topup_route(country):
    """'local', 'international' (live), 'international_soon' (not on yet) or 'usdt'."""
    country = (country or '').upper()
    if country in LOCAL_TOPUP_COUNTRIES:
        return 'local'
    if not country or country in GUARDARIAN_UNSUPPORTED:
        return 'usdt'
    return 'international' if conf.get('ASSISTANT_INTERNATIONAL_TOPUP_ENABLED') else 'international_soon'
