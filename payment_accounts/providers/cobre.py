from decimal import Decimal

from django.conf import settings

from payment_accounts.clients import CobreClient, first_item, verify_cobre_signature

from .base import PaymentAccountProvider, ProviderCapabilityError
from .common import ProviderResult, account_status, operation_status


class CobreProvider(PaymentAccountProvider):
    provider = 'cobre'

    def __init__(self, client=None):
        self.client = client or CobreClient()

    def provision_profile(self, profile):
        # Cobre has no public Account Owner resource equivalent. Confío's
        # verified identity snapshot is the holder record used for key creation.
        return ProviderResult('', 'active', 'LOCAL_VERIFIED', profile.identity_snapshot)

    def provision_account(self, financial_account):
        if financial_account.country != 'COL' or financial_account.asset != 'COP':
            raise ProviderCapabilityError('Cobre Colombia balances require COL/COP')
        alias = f'Confio {financial_account.internal_id}'
        response = first_item(self.client.find_account(alias))
        if not response:
            response = self.client.create_account(
                {
                    'provider_id': getattr(
                        settings, 'COBRE_COLOMBIA_PROVIDER_ID', 'pr_col_cobre'
                    ),
                    'action': 'create',
                    'alias': alias,
                    'tags': [
                        'confio', str(financial_account.provider_profile.confio_account_id)
                    ],
                }
            )
        status, raw_status = account_status(response)
        balance = Decimal(str(response.get('obtained_balance') or 0)) / Decimal('100')
        return ProviderResult(
            resource_id=str(response['id']),
            status=status,
            provider_status=raw_status,
            raw=response,
            available_balance=balance,
            current_balance=balance,
        )

    def sync_account(self, financial_account):
        response = self.client.get_account(financial_account.provider_account_id)
        status, raw_status = account_status(response)
        balance = Decimal(str(response.get('obtained_balance') or 0)) / Decimal('100')
        return ProviderResult(
            str(response['id']), status, raw_status, response, balance, balance
        )

    def create_funding_instruction(self, financial_account, *, kind, **kwargs):
        if kind != 'breb_key':
            raise ProviderCapabilityError(f'Cobre does not create {kind} instructions')
        identity = financial_account.provider_profile.identity_snapshot
        document_map = getattr(settings, 'COBRE_DOCUMENT_TYPE_MAP', {})
        document_type = identity.get('document_type', '')
        issuing_country = identity.get('document_issuing_country', '')
        holder = {
            'full_name': identity.get('full_name', ''),
            'id_number': identity.get('document_number', ''),
            'id_type': (
                kwargs.get('provider_document_type')
                or identity.get('provider_document_type')
                or document_map.get(f'{issuing_country}:{document_type}')
                or document_map.get(f'*:{document_type}', '')
            ),
        }
        if not all(holder.values()):
            raise ProviderCapabilityError('Cobre Bre-B holder data is incomplete')
        alias = kwargs.get('alias') or f'Confio {financial_account.internal_id}'
        key_config = kwargs.get('key_config') or 'random'
        if key_config not in {'name', 'id', 'random', 'open_input'}:
            raise ProviderCapabilityError('Unsupported Cobre Bre-B key configuration')
        payload = {
            'alias': alias,
            'key_config': key_config,
            'holder': holder,
        }
        if key_config == 'open_input':
            open_input = str(kwargs.get('open_input') or '').strip()
            if not open_input or not open_input.isalnum():
                raise ProviderCapabilityError(
                    'Cobre open_input keys require an alphanumeric value without spaces'
                )
            payload['open_input'] = open_input
        response = first_item(
            self.client.find_key(financial_account.provider_account_id, alias)
        )
        if not response:
            response = self.client.create_key(financial_account.provider_account_id, payload)
        raw_status = str(
            response.get('status')
            or (response.get('connectivity') or {}).get('status')
            or 'processing'
        ).upper()
        status = 'active' if raw_status == 'REGISTERED' else 'pending'
        if raw_status in {'FAILED', 'DISABLED', 'UNREGISTERED'}:
            status = 'failed' if raw_status == 'FAILED' else 'closed'
        return ProviderResult(str(response['id']), status, raw_status, response)

    def create_payout(self, operation):
        if operation.source_account.country != 'COL' or operation.source_account.asset != 'COP':
            raise ProviderCapabilityError('Cobre Bre-B payout requires a Colombia COP balance')
        source_id = operation.source_account.provider_account_id
        destination = dict(operation.external_destination or {})
        counterparty_id = destination.get('provider_counterparty_id')
        if not counterparty_id:
            counterparty_payload = destination.get('counterparty_payload')
            if not counterparty_payload:
                raise ProviderCapabilityError('Cobre payout requires a validated counterparty')
            counterparty = self.client.create_counterparty(
                counterparty_payload,
                idempotency_key=f'{operation.idempotency_key}-cp',
            )
            counterparty_id = counterparty.get('id')
        minor_value = operation.source_amount * Decimal('100')
        if minor_value != minor_value.to_integral_value():
            raise ProviderCapabilityError('Cobre payout amount exceeds provider precision')
        amount_minor = int(minor_value)
        maximum = Decimal(
            str(getattr(settings, 'COBRE_BREB_MAX_AMOUNT_COP', '12110000'))
        )
        if operation.source_amount > maximum:
            raise ProviderCapabilityError(
                'Cobre Bre-B payout exceeds the configured rail limit'
            )
        response = self.client.create_money_movement(
            {
                'amount': amount_minor,
                'source_id': source_id,
                'destination_id': counterparty_id,
                'metadata': {'description': 'Confio payout', 'reference': operation.idempotency_key},
                'checker_approval': False,
                'external_id': operation.idempotency_key,
            },
            idempotency_key=operation.idempotency_key,
        )
        status, raw_status = operation_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def provision_destination(self, destination):
        if destination.kind != 'breb_key' or destination.country != 'COL':
            raise ProviderCapabilityError('Cobre adapter currently supports Colombia Bre-B keys')
        key_value = (destination.details or {}).get('key_value')
        if not key_value:
            raise ProviderCapabilityError('Bre-B destination requires key_value')
        alias = f'Confio {destination.internal_id}'
        response = first_item(self.client.find_counterparty(alias))
        if not response:
            response = self.client.create_counterparty(
                {
                    'geo': 'col',
                    'type': 'breb_key',
                    'alias': alias,
                    'metadata': {
                        'key_value': key_value,
                        'counterparty_fullname': destination.holder_name,
                        'counterparty_id_type': destination.holder_id_type.lower(),
                        'counterparty_id_number': destination.holder_id_number,
                    },
                },
                idempotency_key=f'dest-{destination.internal_id}',
            )
        return ProviderResult(str(response['id']), 'active', 'CREATED', response)

    def create_transfer(self, operation):
        if not operation.source_account or not operation.destination_account:
            raise ProviderCapabilityError('Cobre StableFX requires source and destination balances')
        source_asset = operation.source_account.asset.upper()
        target_asset = operation.destination_account.asset.upper()
        if (source_asset, target_asset) not in {
            ('USD_STABLE', 'COPCO'), ('COPCO', 'USD_STABLE')
        }:
            raise ProviderCapabilityError(
                'Cobre StableFX only supports usd_stable and copco balances; '
                'a Bre-B COP balance cannot be used directly'
            )
        minor_value = operation.source_amount * Decimal('100')
        if minor_value != minor_value.to_integral_value():
            raise ProviderCapabilityError('Cobre StableFX amount exceeds provider precision')
        quote = self.client.create_fx_quote({
            'currency_pair': f'{source_asset.lower()}/{target_asset.lower()}',
            'source_amount': int(minor_value),
            'type': 'static_quote',
        })
        quote_id = quote.get('id')
        if not quote_id:
            raise ProviderCapabilityError('Cobre StableFX quote response has no id')
        response = self.client.create_cross_border_movement(
            {
                'source_id': operation.source_account.provider_account_id,
                'destination_id': operation.destination_account.provider_account_id,
                'forex_quote_id': quote_id,
                'metadata': {'destination_description': 'Confio StableFX conversion'},
                'external_id': operation.idempotency_key,
            },
            idempotency_key=operation.idempotency_key,
        )
        response = {**response, 'confio_fx_quote': quote}
        destination_minor = quote.get('destination_amount')
        if destination_minor is not None:
            response['target_amount'] = str(
                Decimal(str(destination_minor)) / Decimal('100')
            )
        status, raw_status = operation_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def retrieve_operation_by_idempotency(self, operation):
        if operation.operation_type == 'conversion':
            response = first_item(
                self.client.find_cross_border_movement(operation.idempotency_key)
            )
        else:
            response = first_item(self.client.find_money_movement(operation.idempotency_key))
        if not response:
            return None
        status, raw_status = operation_status(response)
        return ProviderResult(str(response['id']), status, raw_status, response)

    def verify_webhook(self, raw_body, headers):
        return verify_cobre_signature(
            raw_body,
            headers.get('event-timestamp', ''),
            headers.get('event-signature', ''),
            getattr(settings, 'COBRE_WEBHOOK_SECRET', ''),
        )

    def normalize_webhook(self, raw_body, headers):
        import json

        payload = json.loads(raw_body.decode('utf-8'))
        content = payload.get('content') or {}
        metadata = content.get('metadata') or {}
        return {
            'event_id': str(payload.get('id') or ''),
            'event_type': str(payload.get('event_key') or ''),
            'payload': payload,
            'resource_id': str(content.get('id') or content.get('transaction_id') or ''),
            'account_id': str(
                content.get('account_id')
                or (content.get('id') if 'account' in str(payload.get('event_key', '')).lower() else '')
                or ''
            ),
            'status': content.get('status'),
            'external_id': content.get('external_id') or metadata.get('mm_external_id'),
            'operation_resource_id': str(metadata.get('money_movement_id') or ''),
        }
