"""DB-only compatibility checks for precomputed wallet replacement proofs."""

WALLET_REENROLLMENT_ASSESSMENT_VERSION = 2


def valid_reenrollment_funding(funding, reason):
    return funding > 0 or (funding == 0 and reason == 'never_funded_wallet')


def wallet_reenrollment_assessment(account):
    value = getattr(account, 'wallet_reenrollment_assessment', None)
    if not isinstance(value, dict):
        return None

    # V2 expanded eligibility; it did not invalidate V1 sponsor-only proofs.
    # Keep ONLY that known-compatible positive result across the rollout.
    # Older refusals must be rescanned, and future versions fail closed.
    compatible_v1 = (
        value.get('version') == 1
        and value.get('status') == 'eligible'
        and value.get('eligible') is True
        and value.get('reason') == 'sponsor_only_empty_wallet'
    )
    if (
        (value.get('version') != WALLET_REENROLLMENT_ASSESSMENT_VERSION
         and not compatible_v1)
        or not account.algorand_address
        or value.get('old_algorand_address') != account.algorand_address
        or not isinstance(value.get('old_bsc_address') or '', str)
        or (value.get('old_bsc_address') or '').lower()
        != (getattr(account, 'bsc_address', None) or '').lower()
        or value.get('status') not in ('eligible', 'ineligible')
    ):
        return None
    if value.get('status') == 'eligible':
        try:
            snapshot_round = int(value.get('snapshot_round') or 0)
            funding = int(value.get('sponsor_funding') or 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if snapshot_round <= 0 or not valid_reenrollment_funding(funding, value.get('reason')):
            return None

    # Reading compatibility never upgrades stored evidence or grants permission
    # to retire an address: completion still checks fresh chain/DB blockers.
    return value
