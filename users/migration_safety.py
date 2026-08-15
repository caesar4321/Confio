import logging

from django.conf import settings

logger = logging.getLogger(__name__)

LEGACY_CONFIO_ASSET_ID = 3198568509
MATERIAL_SPENDABLE_ALGO_MICROS = 100_000
MAX_SPONSORED_REENROLLMENT_MICROALGOS = 1_000_000
# Public on-chain identities, not secrets. The KMS sponsor rotated in 2026;
# historical onboarding payments remain valid provenance for older wallets.
LEGACY_ALGORAND_SPONSOR_ADDRESSES = {
    'ZS2HK5N7BZV46ZZGDOQBGFTN3JSXGAFVJFG33WAEP47JQMASSSJIQL7HI4',
}


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


try:  # pragma: no cover - import shape, not logic
    from algosdk.error import AlgodHTTPError
except Exception:  # pragma: no cover - keeps this module importable without the SDK
    AlgodHTTPError = None


# algod's own wording for "this address holds nothing".
_MISSING_ACCOUNT_PHRASES = ('no accounts found', 'account does not exist')


def _describe_exception(exc):
    """Type and status only. algod embeds the queried address in its error
    bodies, so the message itself is PII on this path."""
    code = getattr(exc, 'code', None)
    return f"{type(exc).__name__}(code={code})" if code is not None else type(exc).__name__


def _looks_like_missing_account(exc):
    """True only for algod's own "this address holds nothing" answer, which is a
    CONFIRMED-empty result rather than a failure to look.

    All three conditions are required, because each alone admits a different
    false positive:
      - the SDK's own exception type, so a wrapper or transport error carrying a
        similar string cannot pass;
      - status 404, so an error with a matching body but a 500 cannot pass;
      - algod's phrasing, because `.code` carries ANY HTTP response from the
        provider and a proxy or routing 404 says nothing about the balance.
    An unrecognised 404 costs the user a retry; a misread error costs them the
    guard, so the strict end is the safe end. (Note that the configured provider
    answers 200 with amount 0 for unfunded addresses, so this path is only
    reached on nodes that genuinely 404.)"""
    if AlgodHTTPError is not None and not isinstance(exc, AlgodHTTPError):
        return False
    if getattr(exc, 'code', None) != 404:
        return False
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
            logger.info("Treating missing address %s as no migration risk: %s", redact_address(address), _describe_exception(exc))
            return {
                'has_material_risk': False,
                'relevant_assets': {},
                'spendable_algo': 0,
                'inspection_failed': False,
            }
        # A node timeout, outage, or malformed response tells us nothing about
        # the balance. Reporting it as "no risk" is what lets a transient blip
        # authorize moving the pointer away from a wallet that still holds funds.
        logger.warning("Could not inspect %s for migration risk: %s", redact_address(address), _describe_exception(exc))
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


def classify_sponsored_empty_wallet(account_info, transactions, address, sponsor_address):
    """Decide whether an inaccessible Algorand wallet can be retired safely.

    This is intentionally narrower than "the balance is small". Every asset
    must be empty and the complete transaction history must contain only
    Confio sponsor funding plus zero-value self opt-ins. Anything unfamiliar
    fails closed and keeps the existing recovery requirement.
    """
    sponsor_addresses = set(LEGACY_ALGORAND_SPONSOR_ADDRESSES)
    if isinstance(sponsor_address, (list, tuple, set)):
        sponsor_addresses.update(value for value in sponsor_address if value)
    elif sponsor_address:
        sponsor_addresses.add(sponsor_address)
    if not address or not sponsor_addresses:
        return {'eligible': False, 'reason': 'missing_address_or_sponsor'}

    assets = account_info.get('assets') or []
    if any(int(asset.get('amount') or 0) != 0 for asset in assets):
        return {'eligible': False, 'reason': 'asset_balance'}
    if account_info.get('apps-local-state') or account_info.get('created-apps') or account_info.get('created-assets'):
        return {'eligible': False, 'reason': 'onchain_state'}

    amount = int(account_info.get('amount') or 0)
    if amount < 0 or amount > MAX_SPONSORED_REENROLLMENT_MICROALGOS:
        return {'eligible': False, 'reason': 'algo_balance'}

    sponsor_funding = 0
    saw_sponsor_funding = False
    for txn in transactions:
        if txn.get('rekey-to'):
            return {'eligible': False, 'reason': 'rekey'}
        txn_type = txn.get('tx-type')
        sender = txn.get('sender')

        if txn_type == 'pay':
            payment = txn.get('payment-transaction') or {}
            if (
                sender not in sponsor_addresses
                or payment.get('receiver') != address
                or payment.get('close-remainder-to')
            ):
                return {'eligible': False, 'reason': 'non_sponsor_payment'}
            sponsor_funding += int(payment.get('amount') or 0)
            saw_sponsor_funding = True
            continue

        if txn_type == 'axfer':
            transfer = txn.get('asset-transfer-transaction') or {}
            if (
                sender != address
                or transfer.get('receiver') != address
                or int(transfer.get('amount') or 0) != 0
                or transfer.get('close-to')
                or transfer.get('sender')
            ):
                return {'eligible': False, 'reason': 'asset_activity'}
            continue

        return {'eligible': False, 'reason': 'unsupported_transaction'}

    if not saw_sponsor_funding or sponsor_funding < amount:
        return {'eligible': False, 'reason': 'unproven_funding'}

    return {
        'eligible': True,
        'reason': 'sponsor_only_empty_wallet',
        'sponsor_funding': sponsor_funding,
        'current_amount': amount,
    }


def inspect_sponsored_empty_wallet_reenrollment(
    algod_client,
    indexer_client,
    address,
    sponsor_address,
    max_pages=10,
):
    """Fetch fresh chain state and complete history, failing closed on errors."""
    try:
        account_info = algod_client.account_info(address)
        snapshot_round = int(account_info.get('round') or 0)
        if snapshot_round <= 0:
            return {'eligible': False, 'reason': 'missing_algod_round'}

        transactions = []
        next_token = None
        for _ in range(max_pages):
            response = indexer_client.search_transactions(
                address=address,
                limit=1000,
                next_page=next_token,
                max_round=snapshot_round,
            )
            indexer_round = int(response.get('current-round') or 0)
            if indexer_round < snapshot_round:
                return {'eligible': False, 'reason': 'indexer_lagging'}
            transactions.extend(response.get('transactions') or [])
            next_token = response.get('next-token')
            if not next_token:
                break
        if next_token:
            return {'eligible': False, 'reason': 'history_too_large'}
        return classify_sponsored_empty_wallet(
            account_info,
            transactions,
            address,
            sponsor_address,
        )
    except Exception as exc:
        logger.warning(
            "Could not verify sponsored-empty reenrollment for %s: %s",
            redact_address(address),
            _describe_exception(exc),
        )
        return {'eligible': False, 'reason': 'inspection_failed'}


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
