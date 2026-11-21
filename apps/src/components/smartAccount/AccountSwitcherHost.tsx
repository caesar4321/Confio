// The account switcher for the homes that are not HomeScreen (the Cuenta
// inteligente home and an inherited account, when either is the active
// context). Same menu, same atomic switch, same overlay as Inicio: the way
// back to the personal wallet is always the avatar in the header.
import React, { useCallback, useMemo } from 'react';
import { useNavigation } from '@react-navigation/native';
import { ProfileMenu } from '../ProfileMenu';
import { AccountSwitchOverlay } from '../AccountSwitchOverlay';
import { useAccount } from '../../contexts/AccountContext';
import { useHeader } from '../../contexts/HeaderContext';
import { useAtomicAccountSwitch } from '../../hooks/useAtomicAccountSwitch';
import { usePendingNotificationSwitch } from '../../hooks/usePendingNotificationSwitch';

export function AccountSwitcherHost() {
  const navigation = useNavigation<any>();
  const { profileMenu } = useHeader();
  const { accounts, activeAccount } = useAccount();
  const { switchAccount, state } = useAtomicAccountSwitch();
  const menuAccounts = useMemo(
    () => accounts.map((a) => (a.type === 'personal' ? { ...a, phone: undefined } : a)),
    [accounts],
  );
  const onSwitch = useCallback((accountId: string) => {
    profileMenu.closeProfileMenu();
    if (accountId !== activeAccount?.id) {
      void switchAccount(accountId);
    }
  }, [profileMenu, switchAccount, activeAccount?.id]);
  // In a smart context the Home tab is the Cuenta inteligente / inherited
  // home, not HomeScreen: a notification's pending switch (personal_0 or
  // business_N first, then its screen) is consumed here, same as Inicio.
  usePendingNotificationSwitch(switchAccount);
  const onCreateBusiness = useCallback(() => {
    profileMenu.closeProfileMenu();
    navigation.navigate('CreateBusiness');
  }, [profileMenu, navigation]);

  return (
    <>
      <ProfileMenu
        visible={profileMenu.showProfileMenu}
        onClose={profileMenu.closeProfileMenu}
        accounts={menuAccounts}
        selectedAccount={activeAccount?.id || ''}
        onAccountSwitch={onSwitch}
        onCreateBusinessAccount={onCreateBusiness}
      />
      <AccountSwitchOverlay visible={state.isLoading} progress={state.progress} />
    </>
  );
}

/** Switch back to the personal wallet (used by the smart homes' empty states). */
export function useReturnToPersonal() {
  const { switchAccount, state } = useAtomicAccountSwitch();
  return { returnToPersonal: () => switchAccount('personal_0'), switching: state.isLoading, progress: state.progress };
}
