"""Enforce signed collector transfers and recognize only confirmed collection."""
import json
from decimal import Decimal

from .infinia_fee_funding import collection_call


def mint_policy_calls(calls, user, wallet, request_id):
    """Return the vault-policy subset; signature verification still uses ALL calls."""
    from cusd_plus.sponsor_7702 import PolicyError, SEL_CUSD_MINT, SEL_SUBSCRIBE_AND_MINT, SEL_APPROVE
    from cusd_plus import vault
    from .activity import local_mint_journey_id, mint_request_id
    from .models import InfiniaJourney

    arrivals = InfiniaJourney.objects.filter(direction='to_wallet', wallet_address__iexact=wallet, bridge__status='delivered')
    journey_id = local_mint_journey_id(request_id)
    journey = arrivals.filter(internal_id=journey_id).select_related('money_flow', 'bridge').first() if journey_id else None
    from .infinia_fee_debt import finalize_incoming
    fee = finalize_incoming(journey) if journey else None
    if fee:
        if journey.confio_account.user_id != user.pk:
            raise PolicyError('local_mint_owner_required')
        from .infinia_maintenance import require_reservation
        require_reservation(fee, journey.money_flow)
        # Replay is recognized later by the sponsor. Permit the same exact calls
        # for confirmed/sent attempts, but never authorize a new retry while an
        # earlier attempt may have executed.
        prefix = mint_request_id(journey)
        if request_id not in (prefix + '_a0', prefix + '_a1'):
            raise PolicyError('local_fee_retry_not_allowed')
        from blockchain.models import SponsoredBatch
        if SponsoredBatch.objects.filter(user=user, user_bsc_address__iexact=wallet,
                client_request_id__in=[prefix + '_a0', prefix + '_a1']).exclude(
                client_request_id=request_id).exclude(status__in=['reverted', 'noop_failed']).exists():
            raise PolicyError('local_fee_attempt_already_pending')
        expected = collection_call(fee)
        if not calls or calls[-1] != expected or calls.count(expected) != 1:
            raise PolicyError('local_fee_transfer_required')
        base = calls[:-1]
        mints = [c for c in base if c['to'] == fee['token'] and c['data'][2:10] == SEL_CUSD_MINT]
        if len(mints) != 1 or len(base) not in (1, 2) or base[-1] != mints[0]:
            raise PolicyError('local_fee_requires_cusd_mint')
        if len(base) == 2:
            from .allbridge_next import TOKENS
            approve = base[0]
            if (approve['to'] != TOKENS['BSC:USDT'][0] or approve['data'][2:10] != SEL_APPROVE
                    or len(approve['data']) != 138
                    or approve['data'][10:74] != fee['token'][2:].rjust(64, '0')):
                raise PolicyError('local_mint_approve_not_allowed')
        mint = mints[0]['data']
        if len(mint) != 202:
            raise PolicyError('bad_calldata')
        amount, minimum = int(mint[10:74], 16), int(mint[74:138], 16)
        if amount != int(journey.bridge.actual_out_units):
            raise PolicyError('local_mint_amount_mismatch')
        if minimum < int(fee['units']) + int(fee['minimum_net_units']):
            raise PolicyError('local_mint_net_below_minimum')
        return base
    # Modified/old clients cannot mint reserved local dollars under a generic
    # request identity to omit the collector call. Existing unrelated balances
    # remain usable. Apply this guard only while fee-bearing arrivals are pending.
    pending = arrivals.exclude(wallet_conversion__status='COMPLETED').filter(
        money_flow__metadata__has_key='infinia_fee')
    if pending.exists():
        mint_amount = sum(int(c['data'][10:74], 16) for c in calls
                          if c['data'][2:10] in (SEL_CUSD_MINT, SEL_SUBSCRIBE_AND_MINT))
        available = max(0, vault.usdt_balance_raw(wallet, fresh=True) - vault.reserved_usdt_wei(user, wallet))
        if journey and not journey.money_flow.metadata.get('infinia_fee'):
            available += int(journey.bridge.actual_out_units)
        if mint_amount > available:
            raise PolicyError('local_mint_request_required')
    return calls


def collection_evidence(journey):
    """A successful atomic batch proves its exact collector call executed."""
    from blockchain.models import SponsoredBatch
    from .activity import local_mint_journey_id
    fee = journey.money_flow.metadata.get('infinia_fee')
    if not fee:
        return None
    if journey.direction == 'to_bank':
        batch = journey.bridge.batch if journey.bridge_id and journey.bridge.batch_id else None
        if batch and (batch.kind != 'payment_bridge'
                      or batch.client_request_id != 'bridge:' + str(journey.bridge.internal_id)):
            return None
    else:
        if not journey.wallet_conversion_id or journey.wallet_conversion.status != 'COMPLETED':
            return None
        batch = SponsoredBatch.objects.filter(user=journey.confio_account.user,
            tx_hash__iexact=journey.wallet_conversion.to_transaction_hash,
            user_bsc_address__iexact=journey.wallet_address, status='confirmed').first()
        if batch and local_mint_journey_id(batch.client_request_id) != str(journey.internal_id):
            return None
    if (not batch or batch.status != 'confirmed' or batch.user_id != journey.confio_account.user_id
            or batch.user_bsc_address.lower() != journey.wallet_address.lower()):
        return None
    calls = json.loads(batch.calls_json)
    if calls.count(collection_call(fee)) != 1:
        return None
    return {'status': 'collected', 'transaction_hash': batch.tx_hash,
            'units': fee['units'], 'token': fee['token'], 'collector': fee['collector']}


def wallet_received(journey):
    if not journey.wallet_conversion_id or journey.wallet_conversion.status != 'COMPLETED':
        return None
    conversion = journey.wallet_conversion
    gross = conversion.net_amount_exact if conversion.net_amount_exact is not None else conversion.to_amount
    fee = journey.money_flow.metadata.get('infinia_fee')
    if fee:
        if not collection_evidence(journey):
            return None
        gross -= Decimal(fee['units']) / Decimal(10**18)
    return gross


def persist_local_fee(batch, raw):
    """Revalidate under the invoice lock in the pre-broadcast batch transaction.

    Initial policy checks precede simulation and signing. A competing attempt
    or a refreshed fee can appear meanwhile; neither may slip past persistence.
    The caller rolls back the signed row on failure and never broadcasts it.
    """
    from .activity import local_mint_journey_id
    from .models import InfiniaJourney, MoneyFlow
    journey_id = local_mint_journey_id(batch.client_request_id)
    if not journey_id:
        return
    journey = InfiniaJourney.objects.filter(internal_id=journey_id,
        confio_account__user=batch.user, wallet_address__iexact=batch.user_bsc_address).first()
    if not journey:
        return
    flow = MoneyFlow.objects.select_for_update().get(pk=journey.money_flow_id)
    if flow.metadata.get('infinia_fee'):
        mint_policy_calls(json.loads(batch.calls_json), batch.user,
                          batch.user_bsc_address, batch.client_request_id)


def persist_bridge_fee(owner, flow_id, calls):
    """A prepared bridge must still own its invoices when its batch commits."""
    from .models import MoneyFlow
    from .infinia_maintenance import require_reservation
    from cusd_plus.sponsor_7702 import PolicyError
    # Invoice release and new quotes use this same owner lock.
    type(owner).objects.select_for_update().get(pk=owner.pk)
    flow = MoneyFlow.objects.select_for_update().get(pk=flow_id)
    fee = flow.metadata.get('infinia_fee')
    if fee:
        require_reservation(fee, flow)
        if calls.count(collection_call(fee)) != 1:
            raise PolicyError('local_fee_transfer_required')
