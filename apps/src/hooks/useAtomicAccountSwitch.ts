import { useState, useCallback, useRef } from 'react';
import { Alert } from 'react-native';
import { useApolloClient } from '@apollo/client';
import { useAuth } from '../contexts/AuthContext';
import { useAccount } from '../contexts/AccountContext';
import { AuthService } from '../services/authService';
import { AccountManager } from '../utils/accountManager';

interface AccountSwitchState {
  isLoading: boolean;
  error: string | null;
  progress: string;
}

interface UseAtomicAccountSwitchReturn {
  switchAccount: (accountId: string) => Promise<boolean>;
  state: AccountSwitchState;
  isAccountSwitchInProgress: boolean;
}

/**
 * Hook for atomic account switching that ensures all state is synchronized
 * This prevents partial account switches where some parts of the app think
 * we're in one account while others think we're in another
 */
export const useAtomicAccountSwitch = (): UseAtomicAccountSwitchReturn => {
  const [state, setState] = useState<AccountSwitchState>({
    isLoading: false,
    error: null,
    progress: '',
  });

  // Use a ref to track if switch is in progress to prevent concurrent switches
  const switchInProgressRef = useRef(false);

  const apolloClient = useApolloClient();
  const { refreshProfile } = useAuth();
  const { accounts, refreshAccounts } = useAccount();
  const authService = AuthService.getInstance();
  const accountManager = AccountManager.getInstance();

  // Use refs for frequently-changing deps to keep switchAccount identity stable
  const accountsRef = useRef(accounts);
  accountsRef.current = accounts;
  const refreshProfileRef = useRef(refreshProfile);
  refreshProfileRef.current = refreshProfile;
  const refreshAccountsRef = useRef(refreshAccounts);
  refreshAccountsRef.current = refreshAccounts;

  const switchAccount = useCallback(async (accountId: string): Promise<boolean> => {
    // Prevent concurrent account switches
    if (switchInProgressRef.current) {
      console.warn('Account switch already in progress, ignoring request');
      Alert.alert(
        'Cambio en progreso',
        'Ya hay un cambio de cuenta en progreso. Por favor espera a que termine.',
        [{ text: 'OK' }]
      );
      return false;
    }

    switchInProgressRef.current = true;
    setState({ isLoading: true, error: null, progress: 'Iniciando cambio de cuenta...' });

    try {
      console.log('🔄 [AtomicAccountSwitch] Starting account switch to:', accountId);

      // Step 1: Validate the target account exists
      setState(prev => ({ ...prev, progress: 'Validando cuenta...' }));
      const targetAccount = accountsRef.current.find(acc => acc.id === accountId);
      if (!targetAccount) {
        throw new Error('Cuenta no encontrada');
      }

      console.log('✅ [AtomicAccountSwitch] Target account found:', {
        id: targetAccount.id,
        type: targetAccount.type,
        name: targetAccount.name,
        businessId: targetAccount.business?.id,
      });

      // Step 2: Pause all queries to prevent race conditions
      setState(prev => ({ ...prev, progress: 'Pausando consultas activas...' }));
      apolloClient.stop();
      console.log('⏸️ [AtomicAccountSwitch] Apollo queries paused');

      // Step 3: Clear Apollo cache to prevent stale data
      setState(prev => ({ ...prev, progress: 'Limpiando caché...' }));
      try {
        await apolloClient.cache.reset();
        console.log('🧹 [AtomicAccountSwitch] Apollo cache cleared');
      } catch (cacheError) {
        console.warn('Warning clearing cache:', cacheError);
        // Continue anyway - cache clear is not critical
      }

      // Step 4: Update account context in Keychain
      setState(prev => ({ ...prev, progress: 'Actualizando contexto de cuenta...' }));
      const accountContext = {
        type: targetAccount.type as 'personal' | 'business',
        index: targetAccount.index || 0,
        businessId: targetAccount.business?.id,
      };

      await accountManager.setActiveAccountContext(accountContext);
      console.log('💾 [AtomicAccountSwitch] Account context saved to Keychain');

      // Step 5: Get new JWT token with the updated account context
      setState(prev => ({ ...prev, progress: 'Obteniendo nuevo token de autenticación...' }));
      await authService.switchAccount(accountId, apolloClient);
      console.log('🎫 [AtomicAccountSwitch] New JWT token obtained');

      // Step 6: Small delay to ensure token propagation
      await new Promise(resolve => setTimeout(resolve, 300));

      // Step 7: Refresh profile with new account context
      setState(prev => ({ ...prev, progress: 'Actualizando perfil...' }));
      try {
        if (targetAccount.type === 'business' && targetAccount.business?.id) {
          await refreshProfileRef.current('business', targetAccount.business.id);
          console.log('👤 [AtomicAccountSwitch] Business profile refreshed');
        } else {
          await refreshProfileRef.current('personal');
          console.log('👤 [AtomicAccountSwitch] Personal profile refreshed');
        }
      } catch (profileError) {
        console.error('Error refreshing profile:', profileError);
        // Continue - profile refresh failure shouldn't break the switch
      }

      // Step 8: Refresh accounts to update UI
      setState(prev => ({ ...prev, progress: 'Actualizando lista de cuentas...' }));
      await refreshAccountsRef.current();
      console.log('📋 [AtomicAccountSwitch] Accounts list refreshed');

      // Step 9: Resume Apollo queries
      setState(prev => ({ ...prev, progress: 'Reiniciando consultas...' }));
      apolloClient.reFetchObservableQueries();
      console.log('▶️ [AtomicAccountSwitch] Apollo queries resumed');

      // Step 10: Final validation - ensure everything is in sync
      setState(prev => ({ ...prev, progress: 'Validando sincronización...' }));
      const newContext = await authService.getActiveAccountContext();
      const contextMatchesTarget = (
        newContext.type === targetAccount.type &&
        (newContext.businessId || '') === (targetAccount.business?.id || '')
      );

      if (!contextMatchesTarget) {
        throw new Error('La sincronización de cuenta falló. Por favor intenta nuevamente.');
      }

      console.log('✅ [AtomicAccountSwitch] Account switch completed successfully');
      setState({ isLoading: false, error: null, progress: '' });
      switchInProgressRef.current = false;

      return true;

    } catch (error) {
      console.error('❌ [AtomicAccountSwitch] Account switch failed:', error);

      // Attempt to recover by resuming queries
      try {
        apolloClient.reFetchObservableQueries();
      } catch (recoveryError) {
        console.error('Failed to resume queries:', recoveryError);
      }

      const errorMessage = error instanceof Error ? error.message : 'Error desconocido';
      setState({
        isLoading: false,
        error: errorMessage,
        progress: ''
      });

      Alert.alert(
        'Error al cambiar cuenta',
        `No se pudo cambiar la cuenta: ${errorMessage}`,
        [{ text: 'OK' }]
      );

      switchInProgressRef.current = false;
      return false;
    }
  }, [apolloClient, authService, accountManager]);

  return {
    switchAccount,
    state,
    isAccountSwitchInProgress: switchInProgressRef.current,
  };
};