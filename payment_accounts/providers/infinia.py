from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings

from payment_accounts.clients import InfiniaClient, first_item, verify_infinia_signature
from payment_accounts.compliance import build_infinia_self_declared_payload
from security.didit import (
    retrieve_didit_decision,
    retrieve_linked_didit_decision,
    verification_values_from_didit_decision,
)

from .base import PaymentAccountProvider, ProviderCapabilityError
from .common import ProviderResult, account_status, iso_alpha2, operation_status


class InfiniaProvider(PaymentAccountProvider):
    provider = 'infinia'

    def __init__(self, client=None):
        self.client = client or InfiniaClient()

    def provision_profile(self, profile):
        if profile.kyc_mode != 'SELF_DECLARED':
            raise ProviderCapabilityError('Infinia requires Didit-backed SELF_DECLARED KYC/KYB')
        consent = (profile.provider_data or {}).get('compliance_consent') or {}
        if not consent.get('granted'):
            raise ProviderCapabilityError('Didit data-sharing consent is required')
        existing = first_item(self.client.find_owner(str(profile.internal_id)))
        if existing:
            status, raw_status = account_status(existing)
            return ProviderResult(str(existing['id']), status, raw_status, existing)
        didit = ((profile.identity_verification.risk_factors or {}).get('didit') or {})
        session_id = str(didit.get('session_id') or '')
        if not session_id:
            raise ProviderCapabilityError('Verified Didit session ID is missing')
        account_type = 'business' if profile.owner_type == 'business' else 'personal'
        business_id = (
            str(profile.confio_account.business_id)
            if profile.owner_type == 'business'
            else None
        )
        decision = retrieve_didit_decision(
            session_id=session_id,
            expected_user=profile.confio_account.user,
            expected_account_type=account_type,
            expected_business_id=business_id,
        )
        child_decisions = {}
        if profile.owner_type == 'business':
            for check in decision.get('key_people_checks') or []:
                parties = ((check.get('submitted') or {}).get('parties') or [])
                for party in parties:
                    raw_roles = party.get('roles') or []
                    if isinstance(raw_roles, str):
                        raw_roles = [raw_roles]
                    roles = set()
                    for item in raw_roles:
                        item_role = item.get('role') if isinstance(item, dict) else item
                        normalized = str(item_role or '').strip().lower()
                        if normalized:
                            roles.add(normalized)
                    role = str(party.get('role') or '').strip().lower()
                    if role:
                        roles.add(role)
                    child_id = str(party.get('kyc_session_id') or '')
                    if 'ubo' not in roles or not child_id or child_id in child_decisions:
                        continue
                    child = retrieve_linked_didit_decision(session_id=child_id)
                    if str(child.get('status') or '').strip().lower() != 'approved':
                        raise ProviderCapabilityError('Every UBO must complete Didit KYC')
                    child['_identity'] = SimpleNamespace(
                        **verification_values_from_didit_decision(child)
                    )
                    child_decisions[child_id] = child
        payload, audit_documents = build_infinia_self_declared_payload(
            profile=profile,
            client=self.client,
            decision=decision,
            child_decisions=child_decisions,
        )
        response = self.client.create_owner(payload)
        response = dict(response)
        response['_confio_compliance_handoff'] = {
            'source': 'didit',
            'didit_session_id': session_id,
            'kyc_mode': 'SELF_DECLARED',
            'documents': audit_documents,
        }
        status, raw_status = account_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def sync_profile(self, profile):
        response = self.client.get_owner(profile.provider_owner_id)
        status, raw_status = account_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def provision_account(self, financial_account):
        callback_base = getattr(settings, 'PAYMENT_ACCOUNTS_CALLBACK_BASE_URL', '').rstrip('/')
        payload = {
            'currency': financial_account.asset,
            'country': iso_alpha2(financial_account.country),
            'label': f'Confio {financial_account.internal_id}',
            'products': ['PAYOUTS', 'PAYINS', 'INTERNAL_TRANSFER'],
            'idempotency_key': str(financial_account.internal_id),
            'owner_id': financial_account.provider_profile.provider_owner_id,
        }
        if callback_base:
            payload.update(
                {
                    'webhook_url': f'{callback_base}/api/payment-accounts/infinia/webhook/',
                    'status_callback_url': f'{callback_base}/api/payment-accounts/infinia/webhook/',
                }
            )
        response = self.client.create_account(payload)
        status, raw_status = account_status(response)
        available, current = self._balances(response)
        return ProviderResult(
            str(response['id']),
            status,
            raw_status,
            response,
            available,
            current,
        )

    def sync_account(self, financial_account):
        response = self.client.get_account(financial_account.provider_account_id)
        status, raw_status = account_status(response)
        available, current = self._balances(response)
        return ProviderResult(
            str(response['id']), status, raw_status, response, available, current
        )

    @staticmethod
    def _balances(response):
        balance_data = response.get('balance_details') or response.get('balance') or {}
        if not isinstance(balance_data, dict):
            balance_data = {'total': balance_data}
        available = balance_data.get(
            'available', response.get('available_balance', balance_data.get('total', 0))
        )
        current = balance_data.get(
            'total', balance_data.get('current', response.get('current_balance', 0))
        )
        return Decimal(str(available or 0)), Decimal(str(current or 0))

    def create_funding_instruction(self, financial_account, *, kind, **kwargs):
        raise ProviderCapabilityError(
            'Infinia funding instructions are returned by the account resource'
        )

    def create_payout(self, operation):
        destination = (operation.external_destination or {}).get('destination_account')
        if not destination:
            raise ProviderCapabilityError('Infinia payout destination is incomplete')
        payload = {
            'originId': operation.idempotency_key,
            'amount': float(operation.source_amount),
            'sourceAccountId': operation.source_account.provider_account_id,
            'destinationAccount': destination,
        }
        callback_base = getattr(settings, 'PAYMENT_ACCOUNTS_CALLBACK_BASE_URL', '').rstrip('/')
        if callback_base:
            payload['callbackUrl'] = f'{callback_base}/api/payment-accounts/infinia/webhook/'
        response = self.client.create_payout(payload)
        status, raw_status = operation_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def provision_destination(self, destination):
        # Infinia accepts the destination inline on each payout. We retain a
        # validated, immutable-by-operation local snapshot rather than inventing
        # a provider resource that does not exist.
        if not destination.details:
            raise ProviderCapabilityError('Infinia destination details are incomplete')
        return ProviderResult('', 'active', 'INLINE', destination.details)

    def create_transfer(self, operation):
        if not operation.source_account or not operation.destination_account:
            raise ProviderCapabilityError('Infinia internal transfer requires both accounts')
        payload = {
            'idempotency_key': operation.idempotency_key,
            'source_account_id': operation.source_account.provider_account_id,
            'target_account_id': operation.destination_account.provider_account_id,
            'source_amount': float(operation.source_amount),
        }
        quote_id = (operation.provider_data or {}).get('quote_id')
        if quote_id:
            payload['quote_id'] = quote_id
        callback_base = getattr(settings, 'PAYMENT_ACCOUNTS_CALLBACK_BASE_URL', '').rstrip('/')
        if callback_base:
            payload['callback_url'] = (
                f'{callback_base}/api/payment-accounts/infinia/webhook/'
            )
        response = self.client.create_internal_transfer(payload)
        status, raw_status = operation_status(response)
        if raw_status == 'COMPLETED':
            status = 'settling'
        return ProviderResult(str(response['id']), status, raw_status, response)

    def retrieve_operation_by_idempotency(self, operation):
        response = first_item(
            self.client.find_operation(operation.operation_type, operation.idempotency_key)
        )
        if not response:
            return None
        status, raw_status = operation_status(response)
        if operation.operation_type in {'internal_transfer', 'conversion'} and raw_status == 'COMPLETED':
            status = 'settling'
        return ProviderResult(str(response['id']), status, raw_status, response)

    def verify_webhook(self, raw_body, headers):
        return verify_infinia_signature(
            raw_body,
            headers.get('X-Infinia-Signature', ''),
            getattr(settings, 'INFINIA_SECRET_ID', ''),
        )

    def normalize_webhook(self, raw_body, headers):
        import json

        payload = json.loads(raw_body.decode('utf-8'))
        event_type = str(headers.get('event') or '')
        idempotency_key = (
            payload.get('originId')
            or payload.get('origin_id')
            or payload.get('reference')
            or payload.get('idempotency_key')
        )
        return {
            'event_id': str(headers.get('X-Idempotency-Key') or ''),
            'event_type': event_type,
            'payload': payload,
            'resource_id': str(payload.get('id') or ''),
            'account_id': str(
                payload.get('account_id')
                or payload.get('accountId')
                or (payload.get('id') if event_type.lower().startswith('account') else '')
                or ''
            ),
            'status': payload.get('status'),
            'external_id': idempotency_key,
            'operation_resource_id': str(
                ((payload.get('operation') or {}).get('operation_id')) or ''
            ),
        }
