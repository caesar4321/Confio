import logging

from django.conf import settings

logger = logging.getLogger(__name__)

LEGACY_CONFIO_ASSET_ID = 3198568509
MATERIAL_SPENDABLE_ALGO_MICROS = 100_000


def _relevant_asset_ids():
    asset_ids = {
        getattr(settings, 'ALGORAND_CONFIO_ASSET_ID', None),
        getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None),
        getattr(settings, 'ALGORAND_USDC_ASSET_ID', None),
        LEGACY_CONFIO_ASSET_ID,
    }
    return {int(asset_id) for asset_id in asset_ids if asset_id}


def inspect_address_migration_risk(algod_client, address):
    """
    Return a summary of funds that would be hidden if we reassign the account away
    from this address before migration is actually complete.
    """
    if not address:
        return {
            'has_material_risk': False,
            'relevant_assets': {},
            'spendable_algo': 0,
        }

    try:
        account_info = algod_client.account_info(address)
    except Exception as exc:
        logger.info("Treating missing address %s as no migration risk: %s", address, exc)
        return {
            'has_material_risk': False,
            'relevant_assets': {},
            'spendable_algo': 0,
        }

    relevant_ids = _relevant_asset_ids()

    relevant_assets = {}
    for asset in account_info.get('assets', []):
        asset_id = int(asset.get('asset-id') or 0)
        amount = int(asset.get('amount') or 0)
        if asset_id in relevant_ids and amount > 0:
            relevant_assets[asset_id] = amount

    amount = int(account_info.get('amount') or 0)
    min_balance = int(account_info.get('min-balance') or 0)
    spendable_algo = max(0, amount - min_balance)

    return {
        'has_material_risk': bool(relevant_assets) or spendable_algo >= MATERIAL_SPENDABLE_ALGO_MICROS,
        'relevant_assets': relevant_assets,
        'spendable_algo': spendable_algo,
    }


def get_address_reassignment_blocker(algod_client, current_address, new_address, account=None):
    """
    Return a user-facing error if moving the server-side account pointer away from
    the current address would strand funds on the old wallet.

    Policy:
      * V1 or unknown source: block on ANY material value (relevant assets OR
        spendable ALGO above threshold). The V1 sweep must complete atomically
        before the pointer moves.
      * V2 source (account.is_keyless_migrated=True): block ONLY when the old
        V2 address still holds user-owned relevant assets (USDC / cUSD /
        CONFIO / legacy CONFIO). Sponsor-funded leftover ALGO is not user value
        and must not jail the user out of rotating their V2 secret.
    """
    if not current_address or not new_address or current_address == new_address:
        return None

    risk = inspect_address_migration_risk(algod_client, current_address)

    # Unknown callers stay conservative. Once the account is marked migrated,
    # this is a V2 pointer update and leftover ALGO alone should not block it.
    is_v1_source = account is None or not getattr(account, 'is_keyless_migrated', False)

    if is_v1_source:
        blocking = risk['has_material_risk']
    else:
        # V2 -> V2: only relevant assets are user value worth protecting.
        blocking = bool(risk['relevant_assets'])
        if not blocking:
            logger.info(
                "Allowing V2->V2 reassignment %s -> %s (no user-owned assets at risk; "
                "spendable_algo=%s)",
                current_address,
                new_address,
                risk['spendable_algo'],
            )

    if not blocking:
        return None

    details = []
    if risk['relevant_assets']:
        details.append('activos pendientes')
    if is_v1_source and risk['spendable_algo'] >= MATERIAL_SPENDABLE_ALGO_MICROS:
        details.append('ALGO disponible')

    logger.warning(
        "Blocking account address reassignment %s -> %s because the old address still holds value: "
        "assets=%s spendable_algo=%s source=%s",
        current_address,
        new_address,
        risk['relevant_assets'],
        risk['spendable_algo'],
        'v1' if is_v1_source else 'v2',
    )

    detail_text = ' y '.join(details) if details else 'fondos pendientes'
    return (
        "La migracion de la billetera no se completo. "
        f"La direccion anterior todavia tiene {detail_text}. "
        "Completa la migracion antes de cambiar la direccion activa."
    )
