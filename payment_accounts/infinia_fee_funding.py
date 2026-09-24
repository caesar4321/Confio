"""Integer-only budgeting for a cUSD fee and a USDT bridge in one batch."""
from .infinia_fees import FeePricingError


def net_units(gross, bps):
    return gross - (gross * bps + 9999) // 10000


def gross_units(net, bps):
    return (net * 10000 + (10000 - bps) - 1) // (10000 - bps)


def funding_plan(*, budget, fee, wallet_usdt, wallet_cusd, fee_bps):
    """Spend at most budget, using existing cUSD for the collector first.

    wallet_cusd includes redeemable savings. If the fee needs minting from
    USDT, that mint's perimeter fee also comes out of the reviewed budget.
    No floating point, extra debit, or redeem/mint round trip on existing cUSD.
    """
    if any(type(n) is not int or n < 0 for n in
           (budget, fee, wallet_usdt, wallet_cusd, fee_bps)) or fee_bps > 90:
        raise FeePricingError('Invalid funding amounts or conversion fee')
    if fee <= 0 or budget <= fee or budget > wallet_usdt + wallet_cusd:
        raise FeePricingError('Insufficient dollars for transfer and fees')
    existing_fee = min(fee, wallet_cusd)
    mint_net = fee - existing_fee
    mint_gross = gross_units(mint_net, fee_bps)
    if mint_gross > wallet_usdt:
        raise FeePricingError('Insufficient USDT for fee conversion')
    principal_budget = budget - existing_fee - mint_gross
    if principal_budget <= 0:
        raise FeePricingError('Amount is too small after fees')
    wallet_used = min(wallet_usdt - mint_gross, principal_budget)
    redeem_gross = principal_budget - wallet_used
    if redeem_gross + existing_fee > wallet_cusd:
        raise FeePricingError('Insufficient cUSD for transfer and fees')
    redeem_net = net_units(redeem_gross, fee_bps)
    principal = wallet_used + redeem_net
    if principal <= 0:
        raise FeePricingError('Amount is too small after fees')
    return {
        'bridge_units': str(principal), 'fee_units': str(fee),
        'fee_existing_units': str(existing_fee),
        'fee_mint_gross_units': str(mint_gross), 'fee_mint_net_units': str(mint_net),
        'wallet_usdt_units': str(wallet_used + mint_gross),
        'gross_redeem_units': str(redeem_gross), 'redeem_net_units': str(redeem_net),
        'perimeter_fee_units': str(mint_gross - mint_net + redeem_gross - redeem_net),
        'gross_spend_units': str(budget),
    }


def quote_funding(owner, budget, fee):
    from django.conf import settings
    from cusd_plus import vault, cusd_vault
    from . import bridge_chain as chain

    cusd_vault.require_operational()
    usdt = max(0, chain.token_balance('BSC:USDT', owner.bsc_address)
               - vault.reserved_usdt_wei(owner.user, owner.bsc_address))
    cusd = vault.erc20_balance_raw(settings.CUSD_VAULT_ADDRESS, owner.bsc_address)
    if cusd < fee or usdt + cusd < budget:
        shares = vault.erc20_balance_raw(settings.CUSD_PLUS_VAULT_ADDRESS, owner.bsc_address)
        if shares:
            pps = vault.p_plus_wad(fresh=True)
            oracle = vault.current_oracle_price_wad(fresh=True)
            if pps <= 0 or oracle <= 0:
                raise FeePricingError('Invalid savings price')
            available = vault.redeem_gross_usdt_out(shares, pps, oracle)
            if available >= vault.ONDO_MIN_REDEEM_WEI:
                cusd += available
    return funding_plan(budget=budget, fee=fee, wallet_usdt=usdt, wallet_cusd=cusd,
                        fee_bps=cusd_vault.current_fee_bps())


def collection_call(snapshot):
    return {'to': snapshot['token'], 'value': '0',
            'data': '0xa9059cbb' + snapshot['collector'][2:].rjust(64, '0')
                    + f"{int(snapshot['units']):064x}"}


def funding_calls(owner, plan, snapshot):
    """Build a fee-inclusive source batch; preparation never moves money."""
    from django.conf import settings
    from cusd_plus import vault, cusd_vault
    from cusd_plus.sponsor_7702 import SEL_APPROVE, SEL_CUSD_MINT, SEL_CUSD_REDEEM, SEL_UNWRAP_TO_CUSD
    from .allbridge_next import TOKENS
    from . import bridge_chain as chain

    cusd_vault.require_operational()
    cusd = str(settings.CUSD_VAULT_ADDRESS).lower()
    plus = str(settings.CUSD_PLUS_VAULT_ADDRESS).lower()
    if snapshot['token'] != cusd or int(snapshot['units']) != int(plan['fee_units']):
        raise FeePricingError('Fee token or amount changed; request a new quote')
    wallet = max(0, chain.token_balance('BSC:USDT', owner.bsc_address)
                 - vault.reserved_usdt_wei(owner.user, owner.bsc_address))
    if wallet < int(plan['wallet_usdt_units']):
        raise FeePricingError('Wallet balance changed; request a new quote')
    recipient = owner.bsc_address[2:].lower().rjust(64, '0')
    word = lambda value: f'{int(value):064x}'
    calls = []
    required = int(plan['gross_redeem_units']) + int(plan['fee_existing_units'])
    current = vault.erc20_balance_raw(cusd, owner.bsc_address)
    if current < required:
        needed = required - current
        pps = vault.p_plus_wad(fresh=True)
        oracle = vault.current_oracle_price_wad(fresh=True)
        if pps <= 0 or oracle <= 0:
            raise FeePricingError('Invalid savings price')
        target = max(needed, vault.ONDO_MIN_REDEEM_WEI)
        shares = (target * 10**18 + pps - 1) // pps
        for _ in range(8):
            if vault.redeem_gross_usdt_out(shares, pps, oracle) >= target:
                break
            shares += 1
        if (vault.redeem_gross_usdt_out(shares, pps, oracle) < target
                or shares > vault.erc20_balance_raw(plus, owner.bsc_address)):
            raise FeePricingError('Savings balance changed; request a new quote')
        calls.append({'to': plus, 'value': '0', 'data': '0x' + SEL_UNWRAP_TO_CUSD
                      + word(shares) + word(needed) + recipient})
    mint_gross = int(plan['fee_mint_gross_units'])
    if mint_gross:
        preview = cusd_vault.preview_mint_wei(mint_gross)
        if not 0 <= preview.fee_bps <= 90 or preview.net_wei < int(plan['fee_mint_net_units']):
            raise FeePricingError('Conversion fee changed; request a new quote')
        calls.extend([
            {'to': TOKENS['BSC:USDT'][0], 'value': '0', 'data': '0x' + SEL_APPROVE
             + cusd[2:].rjust(64, '0') + word(mint_gross)},
            {'to': cusd, 'value': '0', 'data': '0x' + SEL_CUSD_MINT
             + word(mint_gross) + word(plan['fee_mint_net_units']) + recipient},
        ])
    redeem = int(plan['gross_redeem_units'])
    if redeem:
        preview = cusd_vault.preview_redeem_wei(redeem)
        if not 0 <= preview.fee_bps <= 90 or preview.net_wei < int(plan['redeem_net_units']):
            raise FeePricingError('Conversion fee changed; request a new quote')
        calls.append({'to': cusd, 'value': '0', 'data': '0x' + SEL_CUSD_REDEEM
                      + word(redeem) + word(plan['redeem_net_units']) + recipient})
    calls.append(collection_call(snapshot))
    return calls, dict(plan, fee_units=plan['perimeter_fee_units'],
                       provider_fee_units=plan['fee_units'])
