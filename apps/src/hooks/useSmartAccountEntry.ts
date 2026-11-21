// What the Cuenta inteligente wallet row on Inicio needs: does the viewer
// have the account (then its one number), may they open one, or were they
// named a beneficiary. Three isolated reads; any of them failing still opens
// a real screen (the offer, which shows its own load error), never a broken
// Home and never a guessed balance. The row never opens the old waitlist
// probe: this build always has the real screens.
import { useEffect, useState } from 'react';
import { useNavigation } from '@react-navigation/native';
import { useSmartRead } from '../components/smartAccount/useSmartRead';
import {
  fetchBeneficiaryDesignations, fetchSmartAccountEntry, fetchSmartAccountOfferGate, isSmartAccountOpen,
  isSmartAccountOpening,
  type BeneficiaryDesignation,
} from '../services/smartAccount';
import type { DirectClaimEntry } from '../services/emergencyExit/directClaimStore';

export type SmartAccountEntryTarget =
  | { screen: 'SmartAccountHome' }
  | { screen: 'SmartAccountOffer'; params: { door: 'billeteras' } }
  | { screen: 'BeneficiaryInvite' | 'BeneficiaryClaim' | 'BeneficiaryClaimStatus'; params: { designationId: string } }
  | { screen: 'BeneficiaryClaim'; params: { designationId: string; account: string } }
  | { screen: 'BeneficiaryDesignations' };

type DesignationScreen = 'BeneficiaryInvite' | 'BeneficiaryClaim' | 'BeneficiaryClaimStatus';

/** A designation the viewer can still act on (invitation or accepted). */
export function isOpenDesignation(d: BeneficiaryDesignation): boolean {
  return d.state === 'pending_acceptance' || d.state === 'active';
}

/**
 * Open designations, one per account: a window change creates a second,
 * pending row for the same person and owner next to the active one. That is
 * not another account, so the pending row is folded into the active one.
 */
export function distinctOpenDesignations(list: BeneficiaryDesignation[]): BeneficiaryDesignation[] {
  const open = list.filter(isOpenDesignation);
  const ownerKey = (d: BeneficiaryDesignation) => `${d.ownerHandle ?? ''}|${d.ownerName ?? ''}`.toLowerCase();
  const activeOwners = new Set(open.filter((d) => d.state === 'active').map(ownerKey));
  return open.filter((d) => d.state === 'active' || !activeOwners.has(ownerKey(d)));
}

function claimRunning(d: BeneficiaryDesignation): boolean {
  return !!d.claim && (d.claim.state === 'pending' || d.claim.state === 'executable');
}

/** The screen one designation opens: its invitation, its claim, or its claim's status. */
export function designationScreen(d: BeneficiaryDesignation): DesignationScreen {
  if (d.state === 'pending_acceptance') {
    return 'BeneficiaryInvite';
  }
  return claimRunning(d) ? 'BeneficiaryClaimStatus' : 'BeneficiaryClaim';
}

/**
 * The designation the row speaks for when there are several: an accepted one
 * with a claim running or ready to start comes first (money is waiting), then
 * a pending invitation, then any other accepted one.
 */
export function pickDesignation(list: BeneficiaryDesignation[]): BeneficiaryDesignation | null {
  const open = list.filter(isOpenDesignation);
  return open.find((d) => d.state === 'active' && (claimRunning(d) || d.canClaim || d.canExecute))
    ?? open.find((d) => d.state === 'pending_acceptance')
    ?? open.find((d) => d.state === 'active')
    ?? null;
}

export interface SmartAccountEntryState {
  /** The viewer has a Cuenta inteligente (any billing state). */
  subscriber: boolean;
  /** Its total, a decimal string; null when unknown. */
  totalUsd: string | null;
  canSubscribe: boolean;
  designation: BeneficiaryDesignation | null;
  /**
   * The designations read failed and this phone remembers being named on an
   * account: the row still opens the claim, where the direct (serverless)
   * path is offered plainly.
   */
  offlineDesignation: DirectClaimEntry | null;
  /** Where the row goes: always a real Cuenta inteligente screen. */
  target: SmartAccountEntryTarget;
}

/**
 * Pure: which screen the row opens for a given state. `designationCount` is
 * how many open designations the viewer has: two or more open the list of
 * all of them instead of one picked for them.
 */
export function smartEntryTarget(
  subscriber: boolean,
  canSubscribe: boolean,
  designation: BeneficiaryDesignation | null,
  offline: Pick<DirectClaimEntry, 'designationId' | 'account'> | null = null,
  designationCount: number = designation ? 1 : 0,
): SmartAccountEntryTarget {
  const several = designationCount >= 2;
  if (subscriber) {
    return { screen: 'SmartAccountHome' };
  }
  // An accepted beneficiary (or one with a claim running) must reach the
  // claim from Inicio even when they could also subscribe: the offer only
  // links pending invitations.
  if (designation && designation.state !== 'pending_acceptance') {
    if (several) {
      return { screen: 'BeneficiaryDesignations' };
    }
    return { screen: designationScreen(designation), params: { designationId: designation.designationId } };
  }
  if (canSubscribe) {
    return { screen: 'SmartAccountOffer', params: { door: 'billeteras' } };
  }
  if (designation) {
    if (several) {
      return { screen: 'BeneficiaryDesignations' };
    }
    return { screen: designationScreen(designation), params: { designationId: designation.designationId } };
  }
  if (offline?.designationId) {
    return { screen: 'BeneficiaryClaim', params: { designationId: offline.designationId, account: offline.account } };
  }
  // Everyone else gets the real pitch. Whether they may sign is the
  // server's answer, shown on that screen (canSubscribe / blockedReason).
  return { screen: 'SmartAccountOffer', params: { door: 'billeteras' } };
}

/**
 * The device's own record of designations, read only while the server's
 * list cannot be had. Never shown next to a server answer.
 */
export function useOfflineDesignations(active: boolean): DirectClaimEntry[] {
  const [entries, setEntries] = useState<DirectClaimEntry[]>([]);
  useEffect(() => {
    if (!active) {
      setEntries([]);
      return undefined;
    }
    let live = true;
    import('../services/smartAccountDirect')
      .then((m) => m.loadOfflineDesignations())
      .then((list) => { if (live) { setEntries(list); } })
      .catch(() => { if (live) { setEntries([]); } });
    return () => { live = false; };
  }, [active]);
  return entries;
}

export function useSmartAccountEntry(enabled: boolean): SmartAccountEntryState {
  const navigation = useNavigation<any>();
  const entry = useSmartRead(fetchSmartAccountEntry, { skip: !enabled });
  const gate = useSmartRead(fetchSmartAccountOfferGate, { skip: !enabled });
  const designations = useSmartRead(fetchBeneficiaryDesignations, { skip: !enabled });

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const unsubscribe = navigation?.addListener?.('focus', () => {
      void entry.reload();
      void designations.reload();
    });
    return typeof unsubscribe === 'function' ? unsubscribe : undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, navigation]);

  // Expired (cancelled and returned) is not a subscriber: the row leads to the offer.
  // An account still opening (subscribe out, not reconciled) opens the
  // account screen too, which waits for it: never the sign-up again.
  const subscriber = enabled && (isSmartAccountOpen(entry.data?.status) || isSmartAccountOpening(entry.data?.status));
  const canSubscribe = enabled && !!gate.data?.available && !!gate.data?.canSubscribe;
  const list = enabled ? designations.data ?? [] : [];
  const designation = pickDesignation(list);
  const designationCount = distinctOpenDesignations(list).length;
  const serverListMissing = enabled && designations.failed && designations.data === undefined;
  const offline = useOfflineDesignations(serverListMissing);
  const offlineDesignation = serverListMissing ? offline[0] ?? null : null;
  return {
    subscriber,
    totalUsd: subscriber ? entry.data?.totalUsd ?? null : null,
    canSubscribe,
    designation,
    offlineDesignation,
    target: smartEntryTarget(subscriber, canSubscribe, designation, offlineDesignation, designationCount),
  };
}
