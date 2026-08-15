export type WalletReenrollmentDecision =
  | 'no_collision'
  | 'repair_collision'
  | 'refuse_collision';

type WalletReenrollmentDecisionInput = {
  serverAlgorandAddress?: string | null;
  restoredAlgorandAddress?: string | null;
  legacyAddressWithValue?: string | null;
  reenrollmentOffered: boolean;
};

type RestoredAddressSelectionInput = {
  serverAlgorandAddress?: string | null;
  existingV2Address?: string | null;
  selectedLegacyAddress?: string | null;
  derivedLegacyAddress?: string | null;
  reenrollmentOffered: boolean;
};

export function selectRestoredAddressForCollision({
  serverAlgorandAddress,
  existingV2Address,
  selectedLegacyAddress,
  derivedLegacyAddress,
  reenrollmentOffered,
}: RestoredAddressSelectionInput): string | null {
  // A matching V2 wallet is always the cheapest authoritative answer. A
  // mismatching V2 wallet becomes the repair candidate only when the server
  // has authorized replacement; otherwise preserve a reproducible V1 wallet
  // so an active/ineligible legacy user is not locked out by a stray V2 key.
  if (
    existingV2Address &&
    (existingV2Address === serverAlgorandAddress || reenrollmentOffered)
  ) {
    return existingV2Address;
  }
  // The read-only legacy derivation already produced the collision candidate.
  // Reuse its address instead of invoking the stateful wallet cache before the
  // decision and server commit.
  return selectedLegacyAddress || derivedLegacyAddress || null;
}

export function selectLegacyAddressForServer(
  serverAlgorandAddress: string | null | undefined,
  derivedLegacyAddress: string | null | undefined,
  legacyAddressWithValue: string | null | undefined,
): string | null {
  // Reproducibility is the collision test. An empty legacy wallet that still
  // derives to the server anchor is the correct wallet and must be reused.
  if (serverAlgorandAddress && derivedLegacyAddress === serverAlgorandAddress) {
    return derivedLegacyAddress;
  }
  // Preserve a different legacy wallet only when it contains material value;
  // the later decision will refuse to retire it.
  return legacyAddressWithValue || null;
}

/**
 * A server assessment is permission to repair, never the trigger itself.
 * Reenrollment is considered only after normal wallet restoration produced a
 * different address and the derived legacy wallet was proven not to hold
 * material value.
 */
export function decideWalletReenrollmentAfterRestore({
  serverAlgorandAddress,
  restoredAlgorandAddress,
  legacyAddressWithValue,
  reenrollmentOffered,
}: WalletReenrollmentDecisionInput): WalletReenrollmentDecision {
  if (
    !serverAlgorandAddress ||
    !restoredAlgorandAddress ||
    restoredAlgorandAddress === serverAlgorandAddress
  ) {
    return 'no_collision';
  }
  // A different derived legacy wallet that still holds value is a real
  // collision, but never a repairable one. The server assessment only proves
  // its stored anchor is disposable; it says nothing about this other wallet.
  if (legacyAddressWithValue) return 'refuse_collision';
  return reenrollmentOffered ? 'repair_collision' : 'refuse_collision';
}
