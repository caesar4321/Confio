/**
 * Which wallet a gated action must prove, with no React in the way.
 *
 * This lives apart from useBackupEnforcement so the screens that choose an
 * action - and the tests that pin that choice - do not have to pull in the
 * hook's auth context.
 */
export type EnforcementAction =
    | 'presale'
    | 'presale_bsc'
    | 'transaction'
    | 'app_launch'
    | 'deposit'
    | 'bsc_deposit';

/**
 * Actions that settle on BSC, so the wallet to verify is the registered EVM
 * one. An account migrated to BSC has no Algorand address at all, so asking
 * for one refuses the operation outright: that is correct for the legacy
 * Algorand deposit address (it does not exist for them) and wrong for the
 * presale, which now settles against the BSC curve vault.
 */
export const isBscSigningAction = (action: EnforcementAction): boolean =>
    action === 'bsc_deposit' || action === 'presale_bsc';

/**
 * Which wallet the presale gate must verify, from the chain the server says
 * settles a purchase. The legacy Algorand rail is still live
 * (PRESALE_ALGORAND_CLOSED is false), so this stays a switch rather than a
 * constant: a purchase that settles on Algorand must still prove the
 * Algorand wallet.
 */
export const presaleEnforcementAction = (isBscFlow: boolean): EnforcementAction =>
    isBscFlow ? 'presale_bsc' : 'presale';
