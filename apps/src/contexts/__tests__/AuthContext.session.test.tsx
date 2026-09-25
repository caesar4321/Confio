const mockClient = { query: jest.fn(), mutate: jest.fn() };
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'),
  useApolloClient: () => mockClient,
}));
jest.mock('../../apollo/client', () => ({
  AUTH_KEYCHAIN_SERVICE: 'com.confio.auth', AUTH_KEYCHAIN_USERNAME: 'auth_tokens',
}));
jest.mock('../../apollo/queries', () => ({ GET_ME: 'me', GET_BUSINESS_PROFILE: 'business', GET_USER_ACCOUNTS: 'accounts' }));
jest.mock('../../services/authService', () => ({
  AuthService: { getInstance: () => ({ getActiveAccountContext: async () => ({ type: 'personal', index: 0 }) }) },
  ensureBscAddressRegistered: jest.fn(),
}));
jest.mock('react-native-keychain', () => ({ getGenericPassword: jest.fn() }));
jest.mock('jwt-decode', () => ({ jwtDecode: () => ({ exp: Date.now() / 1000 + 3600 }) }));
const mockAuthenticate = jest.fn(async (..._args: unknown[]) => true);
jest.mock('../../services/biometricAuthService', () => ({
  biometricAuthService: {
    isEnabled: async () => true,
    isSupported: async () => true,
    authenticate: (...args: unknown[]) => mockAuthenticate(...args),
    isPermanentInvalidation: () => false,
  },
}));
jest.mock('../../services/pushNotificationService', () => ({ pushNotificationService: {} }));
jest.mock('../../services/contactService', () => ({
  contactService: { setContactOwner: jest.fn() }, setDefaultPhoneRegion: jest.fn(),
}));
jest.mock('../../utils/deepLinkHandler', () => ({ deepLinkHandler: {} }));
jest.mock('../../services/emergencyExit/banSignal', () => ({ isBanSignaled: async () => false }));
jest.mock('../../services/emergencyExit/store', () => ({ emergencyStore: {} }));

import React from 'react';
import { Alert, AppState, Platform } from 'react-native';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import * as Keychain from 'react-native-keychain';
import { AuthProvider, useAuth } from '../AuthContext';

describe('session loss after biometric unlock', () => {
  let renderer: ReactTestRenderer;
  let authState: ReturnType<typeof useAuth>;
  const authenticatedStates: boolean[] = [];
  const navigationRef = { current: { reset: jest.fn() } };
  const Probe = () => {
    authState = useAuth();
    authenticatedStates.push(authState.isAuthenticated);
    return null;
  };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    authenticatedStates.length = 0;
    AppState.currentState = 'active';
    jest.replaceProperty(Platform, 'OS', 'android');
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({
      password: JSON.stringify({ accessToken: 'access', refreshToken: 'refresh' }),
    });
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', phoneNumber: '123', phoneCountry: 'AR' } } });
    mockClient.mutate.mockResolvedValue({ data: {} });
    mockAuthenticate.mockResolvedValue(true);
  });

  afterEach(async () => {
    await act(async () => { renderer?.unmount(); });
    jest.clearAllTimers();
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  const mount = async () => {
    await act(async () => {
      renderer = create(<AuthProvider navigationRef={navigationRef as any}><Probe /></AuthProvider>);
    });
  };

  it('does not enter Home when startup requests have cleared the session', async () => {
    mockClient.query.mockImplementationOnce(async () => {
      (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
      throw new Error('Token has been invalidated');
    });
    await mount();
    expect(authState!.isAuthenticated).toBe(false);
    expect(authState!.isLoading).toBe(false);
    expect(Alert.alert).toHaveBeenCalledWith('Vuelve a iniciar sesión', expect.stringContaining('misma cuenta'), expect.any(Array));
    expect(navigationRef.current.reset).not.toHaveBeenCalledWith(expect.objectContaining({ routes: [{ name: 'Main' }] }));
  });

  it('keeps a saved session after a temporary profile failure', async () => {
    mockClient.query.mockRejectedValueOnce(new TypeError('Network request failed'));
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('does not sign out when the final startup Keychain read temporarily fails', async () => {
    mockClient.query.mockImplementationOnce(async () => {
      (Keychain.getGenericPassword as jest.Mock).mockRejectedValueOnce(new Error('Keychain temporarily unavailable'));
      return { data: { me: { id: '1', phoneNumber: '123', phoneCountry: 'AR' } } };
    });
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('explains credential loss once when the monitor returns the user to login', async () => {
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
    expect(navigationRef.current.reset).toHaveBeenCalledWith({
      index: 0, routes: [{ name: 'Auth', params: { screen: 'Login' } }],
    });
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(Alert.alert).toHaveBeenCalledTimes(1);
  });

  it.each([
    { phoneNumber: null, phoneCountry: null },
    { phoneNumber: '123', phoneCountry: null },
  ])('opens phone verification without entering Home for an incomplete phone link: %j', async phone => {
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', ...phone } } });
    await mount();
    expect(authenticatedStates).not.toContain(true);
    expect(authState!.isLoading).toBe(false);
    expect(navigationRef.current.reset).toHaveBeenCalledWith({
      index: 0, routes: [{ name: 'Auth', params: { screen: 'PhoneVerification', params: undefined } }],
    });
    expect(await Keychain.getGenericPassword()).toBeTruthy();
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('routes an already open session to phone verification when its phone link is removed', async () => {
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    navigationRef.current.reset.mockClear();
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', phoneNumber: null, phoneCountry: null } } });
    await act(async () => { await authState!.refreshProfile(); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(navigationRef.current.reset).toHaveBeenCalledWith({
      index: 0, routes: [{ name: 'Auth', params: { screen: 'PhoneVerification', params: undefined } }],
    });
    expect(await Keychain.getGenericPassword()).toBeTruthy();
  });

  it('locks instead of ejecting to login when the startup unlock fails, then unlocks in place', async () => {
    mockAuthenticate.mockResolvedValueOnce(false);
    await mount();
    expect(authState!.isAuthenticated).toBe(false);
    expect(authState!.isLocked).toBe(true);
    expect(authState!.isLoading).toBe(false);
    expect(await Keychain.getGenericPassword()).toBeTruthy();
    expect(navigationRef.current.reset).not.toHaveBeenCalled();

    let unlocked = false;
    await act(async () => { unlocked = await authState!.unlockApp(); });
    await act(async () => { jest.advanceTimersByTime(100); });
    expect(unlocked).toBe(true);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
    expect(navigationRef.current.reset).toHaveBeenCalledWith(expect.objectContaining({ routes: [expect.objectContaining({ name: 'Main' })] }));
  });

  it('locks on a failed resume unlock without clearing the session, then re-enters Main', async () => {
    const handlers: Array<(state: string) => unknown> = [];
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.push(handler);
      return { remove: jest.fn() };
    }) as any);
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    navigationRef.current.reset.mockClear();

    mockAuthenticate.mockResolvedValueOnce(false);
    const nowSpy = jest.spyOn(Date, 'now');
    const t0 = Date.now();
    nowSpy.mockReturnValue(t0);
    await act(async () => { await Promise.all(handlers.map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all(handlers.map(h => h('active'))); });
    nowSpy.mockRestore();

    expect(authState!.isLocked).toBe(true);
    expect(authState!.isAuthenticated).toBe(false);
    expect(authState!.profileData).toBeNull();
    expect(await Keychain.getGenericPassword()).toBeTruthy();
    expect(navigationRef.current.reset).not.toHaveBeenCalledWith(
      expect.objectContaining({ routes: [expect.objectContaining({ name: 'Auth' })] }),
    );

    const promptsBeforeUnlock = mockAuthenticate.mock.calls.length;
    await act(async () => { await authState!.unlockApp(); });
    await act(async () => { jest.advanceTimersByTime(100); });
    // One prompt for the unlock itself; checkAuthState must not prompt again.
    expect(mockAuthenticate.mock.calls.length - promptsBeforeUnlock).toBe(1);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
  });

  it('stays locked when the retry also fails', async () => {
    mockAuthenticate.mockResolvedValue(false);
    await mount();
    let unlocked = true;
    await act(async () => { unlocked = await authState!.unlockApp(); });
    expect(unlocked).toBe(false);
    expect(authState!.isLocked).toBe(true);
    expect(authState!.isAuthenticated).toBe(false);
  });

  it('applies the backup-completion route after startup finishes loading', async () => {
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', requiresBackupCompletion: true } } });
    await mount();
    expect(authenticatedStates).not.toContain(true);
    expect(navigationRef.current.reset).toHaveBeenCalledWith({
      index: 0, routes: [{ name: 'Auth', params: { screen: 'BackupCompletion', params: undefined } }],
    });
  });
});
