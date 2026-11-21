// A notification that needs another account context stores a pending switch
// plus the navigation to run after it, then opens the Home tab
// (pushNotificationService / messagingService). Whichever component is the
// Home tab consumes both on focus: HomeScreen for the personal and business
// wallets, the AccountSwitcherHost of the Cuenta inteligente and inherited
// homes otherwise. One implementation so both homes behave the same.
import { useCallback } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { PushNotificationService } from '../services/pushNotificationService';

/** Delay before reading the pending switch, so the screen is fully mounted. */
export const PENDING_SWITCH_READ_DELAY_MS = 100;
/** Delay between a successful switch and the deferred navigation. */
export const PENDING_NAVIGATION_DELAY_MS = 500;

export function usePendingNotificationSwitch(
  handleAccountSwitch: ((accountId: string) => Promise<boolean>) | null | undefined,
) {
  useFocusEffect(
    useCallback(() => {
      const timer = setTimeout(() => {
        const pendingSwitch = PushNotificationService.getPendingAccountSwitch();
        const pendingNavigation = PushNotificationService.getPendingNavigation();

        // Only process if we have BOTH a pending switch AND navigation
        if (pendingSwitch && pendingNavigation && handleAccountSwitch) {
          // Clear first so a second focus (or the other home mounting after
          // the switch) cannot run it twice.
          PushNotificationService.clearPendingAccountSwitch();
          PushNotificationService.clearPendingNavigation();

          handleAccountSwitch(pendingSwitch).then((success) => {
            if (success) {
              // Not cleared on unmount on purpose: the switch itself can swap
              // the Home tab component (smart home -> HomeScreen), and the
              // navigation must still run.
              setTimeout(() => {
                pendingNavigation();
              }, PENDING_NAVIGATION_DELAY_MS);
            }
          }).catch(() => {});
        }
      }, PENDING_SWITCH_READ_DELAY_MS);

      return () => clearTimeout(timer);
    }, [handleAccountSwitch]),
  );
}
