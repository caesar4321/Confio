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
jest.mock('../../services/biometricAuthService', () => ({
  biometricAuthService: { isEnabled: async () => true, isSupported: async () => true, authenticate: async () => true },
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
  const navigationRef = { current: { reset: jest.fn() } };
  const Probe = () => { authState = useAuth(); return null; };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    AppState.currentState = 'active';
    jest.replaceProperty(Platform, 'OS', 'android');
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({
      password: JSON.stringify({ accessToken: 'access', refreshToken: 'refresh' }),
    });
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', phoneNumber: '123', phoneCountry: 'AR' } } });
    mockClient.mutate.mockResolvedValue({ data: {} });
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
});
