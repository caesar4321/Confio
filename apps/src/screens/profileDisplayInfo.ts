// The name and badge at the top of the Perfil screen, per active account.
import { smartSwitcherLabel } from '../utils/smartAccounts';
import type { StoredAccount } from '../utils/accountManager';

export type ProfileDisplayInfo = {
  name: string;
  subtitle: string;
  accountType?: string;
  showAccountType: boolean;
};

export function profileDisplayInfo(params: {
  activeAccount: (Pick<StoredAccount, 'type' | 'name'> & Partial<Pick<StoredAccount, 'smart'>>) | null | undefined;
  userProfile: { firstName?: string | null; username?: string | null } | null | undefined;
  username: string;
  accountsLoading: boolean;
  isUserProfileLoading: boolean;
}): ProfileDisplayInfo {
  const { activeAccount, userProfile, username, accountsLoading, isUserProfileLoading } = params;
  // Only show loading when we have no data yet
  const stillFetching = (accountsLoading && !activeAccount) ||
    (isUserProfileLoading && !userProfile);
  if (stillFetching) {
    return { name: 'Cargando...', subtitle: '', showAccountType: false };
  }

  if (activeAccount) {
    const type = activeAccount.type.toLowerCase();
    if (type === 'personal') {
      // Personal: name and @username (no phone number, no account type label)
      return {
        name: userProfile?.firstName || userProfile?.username || activeAccount.name,
        subtitle: username,
        accountType: '',
        showAccountType: false,
      };
    }
    if (type === 'smart') {
      // Cuenta inteligente (own or inherited): the switcher's own label.
      return {
        name: activeAccount.name,
        subtitle: '',
        accountType: smartSwitcherLabel(activeAccount),
        showAccountType: true,
      };
    }
    // For business accounts, show business info with account type only (no category)
    return { name: activeAccount.name, subtitle: '', accountType: 'Negocio', showAccountType: true };
  }

  // Fallback: name and @username (no account type label)
  return {
    name: userProfile?.firstName || userProfile?.username || 'Sin perfil',
    subtitle: username,
    accountType: '',
    showAccountType: false,
  };
}
