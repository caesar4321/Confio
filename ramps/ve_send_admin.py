"""Ops console for VE bolívar sends (admin → Ramp transactions → envios-ve/).

Sends pay out on their own; this lists the ones that need a person: a
definite refusal (correct the destination, retry with a new key), an unknown
outcome (confirm "NO PAGADO" with the provider before a new key, or mark it
paid), and late or unproven funding. Superusers only; every action is
recorded on the order and bound to the attempt and destination shown.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ramps import ve_pagomovil, ve_send
from ramps.ve_pagomovil import VePagoMovilError


@require_http_methods(['GET', 'POST'])
def send_console(request, admin_site):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method == 'POST':
        _act(request)
        return redirect(request.path)
    rows = []
    for ramp in ve_send._sends().filter(status='PROCESSING').order_by('created_at'):
        section = ve_send._section(ramp)
        rows.append({
            'ramp': ramp,
            'phase': ve_send._phase(ramp),
            'usdt': (Decimal(str(section.get('funded_wei') or section.get('deposit_wei') or '0'))
                     / Decimal(10 ** 18)).quantize(ve_send.MICRO),
            'section': section,
            'bank_name': ve_pagomovil.BANK_NAMES.get((section.get('beneficiary') or {}).get('bank_code') or '', ''),
        })
    return render(request, 'admin/ramps/ve_send_console.html', {
        **admin_site.each_context(request), 'title': 'Envíos en bolívares (Pago Móvil)', 'rows': rows,
    })


def _act(request) -> None:
    ramp = ve_send._sends().filter(pk=request.POST.get('ramp')).first()
    if ramp is None:
        messages.error(request, 'Envío no encontrado.')
        return
    action = request.POST.get('action')
    operator = request.user.get_username()
    key = request.POST.get('payout_key', '')
    try:
        revision = int(request.POST.get('beneficiary_revision') or 0)
    except ValueError:
        messages.error(request, 'Revisión no válida.')
        return
    try:
        if action == 'retry':
            ve_send.retry_payout(ramp, operator=operator, reviewed_key=key, reviewed_revision=revision)
            _sync_now(ramp)
        elif action == 'retry_unpaid':
            if request.POST.get('confirm') != 'NO PAGADO':
                raise VePagoMovilError('Escribe NO PAGADO para confirmar que el proveedor no lo pagó.')
            ve_send.retry_payout(ramp, operator=operator, reviewed_key=key, reviewed_revision=revision,
                                 confirmed_unpaid=True)
            _sync_now(ramp)
        elif action == 'beneficiary':
            beneficiary = {
                'cedula': ve_pagomovil.normalize_cedula(request.POST.get('cedula', '')),
                'phone': ve_pagomovil.normalize_phone(request.POST.get('phone', '')),
                'bank_code': ve_pagomovil.normalize_bank(request.POST.get('bank_code', '')),
            }
            ve_send.update_beneficiary(ramp, beneficiary, operator=operator, reviewed_key=key,
                                       reviewed_revision=revision)
        elif action == 'paid':
            ve_send.mark_paid_manually(ramp, request.POST.get('reference', ''), operator=operator)
        else:
            raise VePagoMovilError('Acción no válida.')
    except VePagoMovilError as exc:
        messages.error(request, str(exc))
        return
    ramp.refresh_from_db()
    messages.success(request, f'{ramp.internal_id}: {ramp.status} · {ramp.status_detail}')


def _sync_now(ramp) -> None:
    """Try the payout right away; the poller retries within a minute."""
    try:
        from ramps.tasks import sync_ve_pagomovil_order
        sync_ve_pagomovil_order.delay(ramp.pk)
    except Exception:  # noqa: BLE001
        pass
