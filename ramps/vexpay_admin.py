"""Ops console for VEXPay bolívar sends (admin → Ramp transactions → VEXPay envíos).

VEXPay converts each funded deposit by hand. Ops tells this console what it
credited; the server then pays the beneficiary when the free balance covers
it. Superusers only; every action is recorded on the order.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from ramps import vexpay, vexpay_offramp
from ramps.models import RampTransaction

ACTION_PHASES = ('funded', 'converted', 'paying', 'credit_pending', 'credit_failed', 'credit_review')


@require_http_methods(['GET', 'POST'])
def offramp_console(request, admin_site):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method == 'POST':
        _act(request)
        return redirect(request.path)
    rows = []
    for ramp in RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=vexpay_offramp.DIRECTION, status='PROCESSING',
    ).order_by('created_at'):
        section = vexpay._section(ramp)
        rows.append({
            'ramp': ramp,
            'phase': vexpay_offramp._phase(ramp),
            'usdt': (Decimal(str(section.get('funded_wei') or section.get('deposit_wei') or '0'))
                     / Decimal(10 ** 18)).quantize(vexpay_offramp.MICRO),
            'section': section,
            'ref': vexpay_offramp.customer_ref(ramp),
        })
    return render(request, 'admin/ramps/vexpay_offramp_console.html', {
        **admin_site.each_context(request), 'title': 'VEXPay envíos en bolívares', 'rows': rows,
    })


def _act(request) -> None:
    ramp = RampTransaction.objects.filter(
        provider=vexpay.PROVIDER, direction=vexpay_offramp.DIRECTION, pk=request.POST.get('ramp'),
    ).first()
    if ramp is None:
        messages.error(request, 'Envío no encontrado.')
        return
    action = request.POST.get('action')
    operator = request.user.get_username()
    try:
        revision = int(request.POST.get('beneficiary_revision') or 0)
    except ValueError:
        messages.error(request, 'Revisión no válida.')
        return
    try:
        if action == 'converted':
            try:
                ves = Decimal(str(request.POST.get('ves_amount', '')).replace(',', '.'))
            except (InvalidOperation, ValueError):
                raise vexpay_offramp.VexPayOffRampError('Monto en bolívares no válido.')
            vexpay_offramp.mark_converted(ramp, ves, operator=operator)
            _pay_now(ramp)
        elif action == 'retry':
            vexpay_offramp.retry_payout(ramp, operator=operator, reviewed_key=request.POST.get('credit_key', ''),
                                        reviewed_revision=revision)
            _pay_now(ramp)
        elif action == 'retry_unpaid':
            if request.POST.get('confirm') != 'NO PAGADO':
                raise vexpay_offramp.VexPayOffRampError('Escribe NO PAGADO para confirmar que VEXPay no lo pagó.')
            vexpay_offramp.retry_payout(ramp, operator=operator, confirmed_unpaid=True,
                                        reviewed_key=request.POST.get('credit_key', ''), reviewed_revision=revision)
            _pay_now(ramp)
        elif action == 'beneficiary':
            beneficiary = {
                'cedula': vexpay.normalize_cedula(request.POST.get('cedula', '')),
                'phone': vexpay.normalize_phone(request.POST.get('phone', '')),
                'bank_code': f"{vexpay.normalize_bank_code(request.POST.get('bank_code', '')):04d}",
                'bank_name': (request.POST.get('bank_name') or '')[:80],
            }
            vexpay_offramp.update_beneficiary(ramp, beneficiary, operator=operator,
                                              reviewed_key=request.POST.get('credit_key', ''),
                                              reviewed_revision=revision)
        elif action == 'paid':
            vexpay_offramp.mark_paid_manually(ramp, request.POST.get('reference', ''), operator=operator)
        else:
            raise vexpay_offramp.VexPayOffRampError('Acción no válida.')
    except vexpay.VexPayRampError as exc:
        messages.error(request, str(exc))
        return
    ramp.refresh_from_db()
    messages.success(request, f'{ramp.internal_id}: {ramp.status} · {ramp.status_detail}')


def _pay_now(ramp: RampTransaction) -> None:
    """Try the payout right away; the poller retries within a minute."""
    try:
        from ramps.tasks import sync_vexpay_ramp_task
        sync_vexpay_ramp_task.delay(ramp.pk)
    except Exception:  # noqa: BLE001
        pass
