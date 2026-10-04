import hashlib
import json
import uuid

from django import forms
from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import StereumTestWebhook
from .stereum_client import StereumClient, StereumError
from .stereum_service import FIELDS, execute, permitted


EXAMPLES = {
    'banks': {}, 'balance': {}, 'orders': {},
    'quote': {'side': 'BUY', 'amount': '1000.00', 'currency': 'USDT'},
    'customer_quote': {'side': 'BUY', 'amount': '1000.00', 'currency': 'USDT'},
    'decode_qr': {'qrs': 'Paste the scanned bank QR string'},
    'charge': {'amount': '1.00', 'name': 'Sandbox', 'lastname': 'Tester', 'document_number': '1234567', 'reason': 'Confio sandbox test'},
    'order': {'quote_request_id': 'Local quote request UUID', 'address': 'Polygon wallet for BUY; bank account for SELL'},
    'pay_qr': {'decode_request_id': 'Local QR decode request UUID', 'amount': '1.00', 'comment': 'Sandbox test', 'sender_name': 'Sandbox Tester', 'sender_document': '1234567'},
    'confirm_charge': {'charge_request_id': 'Local test charge request UUID'},
}


class TestForm(forms.Form):
    action = forms.ChoiceField(choices=[(key, key.replace('_', ' ').title()) for key in FIELDS])
    request_id = forms.UUIDField(help_text='Keep this UUID when retrying the same request.')
    payload = forms.JSONField(required=False, widget=forms.Textarea(attrs={'rows': 12, 'cols': 80}))

    def clean_payload(self):
        value = self.cleaned_data['payload']
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise forms.ValidationError('Payload must be a JSON object.')
        return value


def console(request):
    try:
        permitted(request.user)
    except StereumError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    initial = {'action': 'quote', 'request_id': uuid.uuid4(), 'payload': EXAMPLES['quote']}
    form = TestForm(request.POST if request.method == 'POST' else None, initial=initial)
    operation = None
    if request.method == 'POST' and form.is_valid():
        try:
            operation = execute(request.user, form.cleaned_data['action'], form.cleaned_data['payload'], form.cleaned_data['request_id'])
        except StereumError as exc:
            form.add_error(None, str(exc))
    return render(request, 'admin/ramps/stereum_test_console.html', {
        **admin.site.each_context(request), 'title': 'Stereum test console', 'form': form,
        'operation': operation, 'result': json.dumps(operation.response_data, indent=2, ensure_ascii=False) if operation else '',
        'examples': json.dumps(EXAMPLES, indent=2),
        'writes_enabled': getattr(settings, 'STEREUM_TEST_WRITES_ENABLED', False),
    })


@csrf_exempt
@require_POST
def webhook(request):
    if not getattr(settings, 'STEREUM_TEST_ENABLED', False):
        return JsonResponse({'ok': False}, status=404)
    raw = request.read(262145)
    if len(raw) > 262144:
        return JsonResponse({'ok': False}, status=413)
    try:
        client = StereumClient()
        if not client.verify_webhook(raw, request.headers.get('x-signature', '')):
            return JsonResponse({'ok': False}, status=403)
        payload = json.loads(raw)
        json.dumps(payload, allow_nan=False)
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, RecursionError, StereumError):
        return JsonResponse({'ok': False}, status=400)
    # Notification is evidence, never authoritative settlement. Operators poll the
    # provider resource; duplicate/reordered notifications cannot credit balances.
    digest = hashlib.sha256(client.scope.encode() + raw).hexdigest()
    _, created = StereumTestWebhook.objects.get_or_create(
        digest=digest, defaults={'credential_scope': client.scope, 'payload': payload},
    )
    return JsonResponse({'ok': True, 'duplicate': not created})


class CustomerForm(forms.Form):
    from .stereum_customers import DEPARTMENTS, INCOMES
    state_of_residence = forms.ChoiceField(choices=[(v, v) for v in sorted(DEPARTMENTS)])
    economic_activity = forms.CharField(max_length=200)
    source_of_funds = forms.CharField(max_length=60)
    destination_of_funds = forms.CharField(max_length=60)
    income_level = forms.ChoiceField(choices=[(v, v) for v in sorted(INCOMES)])
    surname1 = forms.CharField(max_length=100, required=False, help_text='First surname exactly as verified. Required for CI/CE.')
    surname2 = forms.CharField(max_length=100, required=False)
    complement_number = forms.CharField(max_length=20, required=False)
    consent = forms.BooleanField(label='I authorize sharing my verified identity and these details with Stereum’s test API.')


def customer_console(request):
    from .stereum_customers import access, current_identity, onboard, onboarding_status
    try:
        permitted(request.user)
        access(request.user)
        identity = current_identity(request.user)
        record = onboarding_status(request.user)
    except StereumError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    initial = {}
    address = getattr(request.user, 'ramp_user_address', None)
    if address and address.economic_activity:
        initial['economic_activity'] = address.economic_activity
    if record:
        initial.update({k: v for k, v in record.request_snapshot['customer'].items() if k in CustomerForm.base_fields})
        validation = record.request_snapshot.get('validation') or {}
        initial.update({k: validation.get(k, '') for k in ('surname1', 'surname2')})
        initial['complement_number'] = validation.get('complementNumber', '')
    form = CustomerForm(request.POST if request.method == 'POST' else None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data)
        consent = data.pop('consent')
        try:
            record = onboard(request.user, data, consent=consent)
        except StereumError as exc:
            form.add_error(None, str(exc))
    return render(request, 'admin/ramps/stereum_customer_console.html', {
        **admin.site.each_context(request), 'title': 'Stereum customer onboarding',
        'identity': identity, 'form': form, 'record': record,
    })
