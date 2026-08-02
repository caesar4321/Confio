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


def redact_address(address):
    """Head+tail only. Enough for a human to match an address they already have,
    not enough to leave the identifier itself sitting in a log file."""
    value = str(address or '')
    return f"{value[:6]}…{value[-4:]}" if len(value) > 14 else '(none)'


# algod's own wording for "this address holds nothing". Anything else that
# arrives with a 404 came from somewhere between us and the node.
_MISSING_ACCOUNT_PHRASES = ('no accounts found', 'account does not exist')


def _looks_like_missing_account(exc):
    """Algod answers 404 with one of these bodies for an address that was never
    funded or was closed out. That is a CONFIRMED-empty answer.

    The BODY is required, not just the status: `.code` carries any HTTP response
    from the provider, so a proxy or routing 404 would otherwise be read as proof
    the account is empty and restore the fail-open this function exists to close.
    A bare `not found` match would do the same to a DNS error ("host not found").
    An unrecognised 404 costs the user a retry; a misread transport error costs
    them the guard."""
    message = str(exc).lower()
    return any(phrase in message for phrase in _MISSING_ACCOUNT_PHRASES)


def inspect_address_migration_risk(algod_client, address):
    """
    Return a summary of funds that would be hidden if we reassign the account away
    from this address before migration is actually complete.

    `inspection_failed` separates "the chain says this address is empty" from "we
    could not read the chain". Callers that gate a security decision must treat
    the second as unknown, never as empty.
    """
    if not address:
        return {
            'has_material_risk': False,
            'relevant_assets': {},
            'spendable_algo': 0,
            'inspection_failed': False,
        }

    try:
        account_info = algod_client.account_info(address)
    except Exception as exc:
        if _looks_like_missing_account(exc):
            logger.info("Treating missing address %s as no migration risk: %s", redact_address(address), exc)
            return {
                'has_material_risk': False,
                'relevant_assets': {},
                'spendable_algo': 0,
                'inspection_failed': False,
            }
        # A node timeout, outage, or malformed response tells us nothing about
        # the balance. Reporting it as "no risk" is what lets a transient blip
        # authorize moving the pointer away from a wallet that still holds funds.
        logger.warning("Could not inspect %s for migration risk: %s", redact_address(address), exc)
        return {
            'has_material_risk': False,
            'relevant_assets': {},
            'spendable_algo': 0,
            'inspection_failed': True,
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
        'inspection_failed': False,
    }


def get_address_reassignment_blocker(algod_client, current_address, new_address, account=None):
    """
    Return a user-facing error if moving the server-side account pointer away from
    the current address would strand funds on the old wallet.

    Policy: block on ANY material value (relevant assets OR spendable ALGO
    above threshold). V2 -> V2 replacement is not a recovery mechanism; the
    client must restore the canonical cloud-backed V2 secret instead.
    """
    if not current_address or not new_address or current_address == new_address:
        return None

    risk = inspect_address_migration_risk(algod_client, current_address)

    if risk.get('inspection_failed'):
        # Fail CLOSED: an unreadable address is unknown, not empty. Refusing a
        # reassignment costs the user a retry; allowing one on an unverified
        # address can strand real funds on a wallet we stop pointing at.
        logger.warning(
            "Blocking account address reassignment %s -> %s: the old address could not be inspected",
            redact_address(current_address),
            redact_address(new_address),
        )
        return (
            "No pudimos verificar tu billetera anterior en este momento. "
            "Revisa tu conexion e intentalo de nuevo en unos minutos."
        )

    if not risk['has_material_risk']:
        return None

    details = []
    if risk['relevant_assets']:
        details.append('activos pendientes')
    if risk['spendable_algo'] >= MATERIAL_SPENDABLE_ALGO_MICROS:
        details.append('ALGO disponible')

    logger.warning(
        "Blocking account address reassignment %s -> %s because the old address still holds value: assets=%s spendable_algo=%s",
        redact_address(current_address),
        redact_address(new_address),
        risk['relevant_assets'],
        risk['spendable_algo'],
    )

    detail_text = ' y '.join(details) if details else 'fondos pendientes'
    return (
        "La migracion de la billetera no se completo. "
        f"La direccion anterior todavia tiene {detail_text}. "
        "Completa la migracion antes de cambiar la direccion activa."
    )
