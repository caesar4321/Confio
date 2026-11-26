const mockClient = { query: jest.fn(), mutate: jest.fn(), clearStore: jest.fn() };
const mockAuthSignOut = jest.fn(async () => {});
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'),
  useApolloClient: () => mockClient,
}));
// The shared refresh (deadline, one request per session, never writes over a
// session that changed) is tested with the client; here it is only watched.
const mockRefreshAccessToken = jest.fn(async (..._args: unknown[]) => 'access-new');
jest.mock('../../apollo/client', () => ({
  refreshAccessToken: (...args: unknown[]) => mockRefreshAccessToken(...args),
}));
jest.mock('../../apollo/queries', () => ({ GET_ME: 'me', GET_BUSINESS_PROFILE: 'business', GET_USER_ACCOUNTS: 'accounts' }));
jest.mock('../../services/authService', () => ({
  AuthService: { getInstance: () => ({
    getActiveAccountContext: async () => ({ type: 'personal', index: 0 }),
    signOut: () => mockAuthSignOut(),
  }) },
  ensureBscAddressRegistered: jest.fn(),
}));
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(),
  // One function shared by this file and AuthContext, so a write is seen.
  setGenericPassword: jest.fn(async () => true),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
}));
// The store's own behaviour is covered in services/__tests__/sessionStore.test.ts.
// Here it reads straight through to the mocked keychain, and a test ends the
// session the way the app sees it: a reset of the stored entry.
const mockResetListeners = new Set<() => void>();
let mockObserverInstalled = true;
// The monitor looks a second after a reset (SESSION_RESET_GRACE_MS).
const mockEmitSessionReset = () => {
  mockResetListeners.forEach(listener => listener());
  jest.advanceTimersByTime(1000);
};
jest.mock('../../services/sessionStore', () => ({
  getSessionCredentials: () => require('react-native-keychain').getGenericPassword(),
  isSessionObserverInstalled: () => mockObserverInstalled,
  onSessionReset: (listener: () => void) => {
    mockResetListeners.add(listener);
    return () => { mockResetListeners.delete(listener); };
  },
}));
jest.mock('../../navigation/RootNavigation', () => ({ navigationRef: { current: null } }));
jest.mock('../../services/linkSend', () => ({
  setLinkOpener: jest.fn(), takeClipboardLink: jest.fn(), takePendingLink: jest.fn(),
}));
let mockExpired = false;
jest.mock('jwt-decode', () => ({ jwtDecode: () => ({ exp: Date.now() / 1000 + (mockExpired ? -1 : 3600) }) }));
const mockAuthenticate = jest.fn(async (..._args: unknown[]) => true);
// The guard item is missing while the "enabled" preference is still there.
let mockGuardGone = false;
// Whether the phone still has its lock set up for Confío.
let mockEnrolled = true;
const mockEnable = jest.fn(async (..._args: unknown[]) => true);
// Confío Face is for money movements only: opening the app must never reach it.
const mockFace = jest.fn(async (..._args: unknown[]) => true);
jest.mock('../../services/faceAuthentication', () => ({
  authenticateWithFace: (...args: unknown[]) => mockFace(...args),
  isFaceAuthenticating: () => false,
}));
jest.mock('../../services/biometricAuthService', () => ({
  biometricAuthService: {
    isEnabled: async () => mockEnrolled,
    isSupported: async () => true,
    authenticate: (...args: unknown[]) => mockAuthenticate(...args),
    isPermanentInvalidation: () => mockGuardGone,
    disable: async () => {},
    enable: (...args: unknown[]) => mockEnable(...args),
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
    mockExpired = false;
    mockGuardGone = false;
    mockEnrolled = true;
    mockEnable.mockReset().mockResolvedValue(true);
    mockRefreshAccessToken.mockReset().mockResolvedValue('access-new');
    mockObserverInstalled = true;
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
    await act(async () => { mockEmitSessionReset(); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
    expect(navigationRef.current.reset).toHaveBeenCalledWith({
      index: 0, routes: [{ name: 'Auth', params: { screen: 'Login' } }],
    });
    await act(async () => { mockEmitSessionReset(); });
    expect(Alert.alert).toHaveBeenCalledTimes(1);
  });

  // protects=a phone-less account (signup no longer asks for one) enters Home; fails_when=any phone gate routes it to PhoneVerification; no_claim=server-side login
  it.each([
    { phoneNumber: null, phoneCountry: null },
    { phoneNumber: '123', phoneCountry: null },
  ])('enters Home without a phone link: %j', async phone => {
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', ...phone } } });
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    expect(JSON.stringify(navigationRef.current.reset.mock.calls)).not.toContain('PhoneVerification');
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('keeps an open session signed in when its phone link is removed', async () => {
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    navigationRef.current.reset.mockClear();
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', phoneNumber: null, phoneCountry: null } } });
    await act(async () => { await authState!.refreshProfile(); });
    expect(authState!.isAuthenticated).toBe(true);
    expect(JSON.stringify(navigationRef.current.reset.mock.calls)).not.toContain('PhoneVerification');
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

  // protects=unlocking resumes the screen the user was on; fails_when=the lock unmounts Main or the unlock resets to it; no_claim=native Modal rendering
  it('keeps Main mounted through a failed resume unlock, then uncovers it in place', async () => {
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
    expect(authState!.isAuthenticated).toBe(true);
    expect(authState!.profileData).not.toBeNull();
    expect(await Keychain.getGenericPassword()).toBeTruthy();

    const promptsBeforeUnlock = mockAuthenticate.mock.calls.length;
    await act(async () => { await authState!.unlockApp(); });
    await act(async () => { jest.advanceTimersByTime(100); });
    // One prompt for the unlock itself; checkAuthState must not prompt again.
    expect(mockAuthenticate.mock.calls.length - promptsBeforeUnlock).toBe(1);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
    expect(authenticatedStates.slice(authenticatedStates.indexOf(true))).not.toContain(false);
    expect(navigationRef.current.reset).not.toHaveBeenCalled();
  });

  it('does not prompt again when the OS prompt itself resumes a locked app', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockAuthenticate.mockResolvedValueOnce(false);
    const nowSpy = jest.spyOn(Date, 'now');
    let t = Date.now();
    const go = async (state: string, advance = 60_000) => {
      nowSpy.mockReturnValue(t += advance);
      await act(async () => { await Promise.all([...handlers].map(h => h(state))); });
    };
    await go('background');
    await go('active');
    const prompts = mockAuthenticate.mock.calls.length;
    await go('inactive');
    await go('active');
    nowSpy.mockRestore();
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(authState!.isLocked).toBe(true);
  });

  // protects=sign-out never uncovers the wallet; fails_when=the lock drops before the session is gone; no_claim=server sign-out
  it('keeps Main covered until sign-out has finished', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockAuthenticate.mockResolvedValueOnce(false);
    const nowSpy = jest.spyOn(Date, 'now');
    const t0 = Date.now();
    nowSpy.mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    let finishSignOut!: () => void;
    mockAuthSignOut.mockImplementationOnce(() => new Promise<void>(resolve => { finishSignOut = resolve; }));
    let signingOut!: Promise<void>;
    await act(async () => { signingOut = authState!.signOut(); });
    expect(authState!.isLocked).toBe(true);
    await act(async () => { finishSignOut(); await signingOut; });
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(false);
  });

  // protects=a person who signs out is not told their session vanished; fails_when=signOut's own keychain reset reaches the session-ended alert; no_claim=sessions ended by the server
  it('does not explain a session the person ended themselves', async () => {
    await mount();
    let finishSignOut!: () => void;
    mockAuthSignOut.mockImplementationOnce(() => new Promise<void>(resolve => { finishSignOut = resolve; }));
    let signingOut!: Promise<void>;
    await act(async () => { signingOut = authState!.signOut(); });
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { mockEmitSessionReset(); });
    await act(async () => { finishSignOut(); await signingOut; });
    await act(async () => { mockEmitSessionReset(); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('still notices a lost session by asking again when the keychain cannot be observed', async () => {
    mockObserverInstalled = false;
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { jest.advanceTimersByTime(15_000); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
  });

  // protects=a person whose session the server ended reaches login; fails_when=one unreadable keychain answer ends the watching; no_claim=how long the keychain stays unreadable
  it('asks again when the keychain cannot be read after a reset', async () => {
    await mount();
    (Keychain.getGenericPassword as jest.Mock).mockRejectedValueOnce(new Error('keystore busy'));
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { mockEmitSessionReset(); });
    expect(authState!.isAuthenticated).toBe(true);
    await act(async () => { jest.advanceTimersByTime(2000); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(Alert.alert).toHaveBeenCalledTimes(1);
  });

  // protects=a flow that clears the session and writes a new one at once; fails_when=a return to the app inside the grace signs the person out; no_claim=flows slower than the grace
  it('a return to the app right after a reset still waits out the grace', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { mockResetListeners.forEach(listener => listener()); });
    await act(async () => { [...handlers].forEach(h => { h('active'); }); });
    expect(authState!.isAuthenticated).toBe(true);
    // The new session is written within the grace.
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({
      password: JSON.stringify({ accessToken: 'access2', refreshToken: 'refresh2' }),
    });
    await act(async () => { jest.advanceTimersByTime(1500); });
    expect(authState!.isAuthenticated).toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  // protects=a clear-then-write flow on a slow keychain; fails_when=a check already waiting on the keychain acts on what it read inside the grace; no_claim=flows slower than the grace
  it('a check that was already reading when the reset landed waits out the grace too', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    let answerRead: (value: unknown) => void = () => {};
    (Keychain.getGenericPassword as jest.Mock).mockImplementationOnce(() => new Promise(resolve => { answerRead = resolve; }));
    await act(async () => { [...handlers].forEach(h => { h('active'); }); });
    // The reset lands while that read is still waiting, then the read answers empty.
    await act(async () => { mockResetListeners.forEach(listener => listener()); answerRead(false); });
    expect(authState!.isAuthenticated).toBe(true);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({
      password: JSON.stringify({ accessToken: 'access2', refreshToken: 'refresh2' }),
    });
    await act(async () => { jest.advanceTimersByTime(1500); });
    expect(authState!.isAuthenticated).toBe(true);
    expect(Alert.alert).not.toHaveBeenCalled();
  });

  it('does not poll the keychain when resets are observed', async () => {
    await mount();
    const readsAfterMount = (Keychain.getGenericPassword as jest.Mock).mock.calls.length;
    await act(async () => { jest.advanceTimersByTime(60_000); });
    expect((Keychain.getGenericPassword as jest.Mock).mock.calls.length).toBe(readsAfterMount);
  });

  it('leaves the lock for login when the session ends while locked', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockAuthenticate.mockResolvedValueOnce(false);
    const nowSpy = jest.spyOn(Date, 'now');
    const t0 = Date.now();
    nowSpy.mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(authState!.isLocked).toBe(true);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    await act(async () => { mockEmitSessionReset(); });
    expect(authState!.isAuthenticated).toBe(false);
    expect(authState!.isLocked).toBe(false);
  });

  // protects=the wallet is never tappable before the phone's unlock, and the prompt never waits on the network; fails_when=the prompt waits for the token refresh, or Main shows before the prompt answers; no_claim=what the refresh itself does (apollo/client)
  it('covers Main and shows the unlock prompt while the token refresh hangs; a cancelled prompt leaves Desbloquear live', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockExpired = true;
    // A dead network: no refresh, by any route, ever answers.
    mockRefreshAccessToken.mockImplementation(() => new Promise<string>(() => {}));
    mockClient.mutate.mockImplementation(() => new Promise(() => {}));
    let answerPrompt!: (ok: boolean) => void;
    mockAuthenticate.mockImplementationOnce(() => new Promise<boolean>(resolve => { answerPrompt = resolve; }));
    const promptsBeforeResume = mockAuthenticate.mock.calls.length;
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { [...handlers].forEach(h => { h('active'); }); });
    nowSpy.mockRestore();
    // The prompt is up and Main is covered, with the refresh still out.
    expect(mockAuthenticate.mock.calls.length - promptsBeforeResume).toBe(1);
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(authState!.isLocked).toBe(true);
    expect(authState!.isAuthenticated).toBe(true);
    await act(async () => { await authState!.signOut(); });
    expect(Alert.alert).toHaveBeenCalledWith('Verificación en curso', expect.any(String));
    expect(await Keychain.getGenericPassword()).toBeTruthy();

    // Cancelled: still locked, and Desbloquear prompts again at once.
    await act(async () => { answerPrompt(false); });
    expect(authState!.isLocked).toBe(true);
    const prompts = mockAuthenticate.mock.calls.length;
    let unlocked = false;
    await act(async () => { unlocked = await authState!.unlockApp(); });
    expect(unlocked).toBe(true);
    expect(mockAuthenticate.mock.calls.length - prompts).toBe(1);
    expect(authState!.isLocked).toBe(false);
    expect(await Keychain.getGenericPassword()).toBeTruthy();
  });

  // protects=resume hands the token write to the shared refresh, and a hung refresh holds neither Main nor sign-out; fails_when=resume sends its own refresh or writes tokens itself, or a passed prompt waits for the refresh before uncovering; no_claim=the shared refresh's own session check (apollo/client)
  it('uncovers Main on a passed prompt while the refresh still hangs, and never writes the session itself', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockExpired = true;
    let finishRefresh!: (token: string) => void;
    mockRefreshAccessToken.mockImplementation(() => new Promise<string>(resolve => { finishRefresh = resolve; }));
    // Were resume still refreshing on its own, this answer would be written.
    mockClient.mutate.mockResolvedValue({ data: { refreshToken: { token: 'access-own' } } });
    mockClient.mutate.mockClear();
    const write = Keychain.setGenericPassword as jest.Mock;
    write.mockClear();
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    let resume!: Promise<unknown[]>;
    await act(async () => { resume = Promise.all([...handlers].map(h => h('active'))); });
    expect(authState!.isLocked).toBe(false);
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockRefreshAccessToken).toHaveBeenCalledWith({ accessToken: 'access', refreshToken: 'refresh' });
    // The prompt has answered, so leaving the account is allowed again.
    await act(async () => { await authState!.signOut(); });
    expect(Alert.alert).not.toHaveBeenCalledWith('Verificación en curso', expect.any(String));
    expect(authState!.isAuthenticated).toBe(false);
    await act(async () => { finishRefresh('access-new'); await resume; });
    nowSpy.mockRestore();
    expect(write).not.toHaveBeenCalled();
    expect(mockClient.mutate.mock.calls.filter(([options]: any[]) => options?.variables?.refreshToken)).toEqual([]);
    expect(authState!.isAuthenticated).toBe(false);
  });

  // protects=a tap on Desbloquear while a resume is still bringing up the prompt is not answered "no"; fails_when=unlockApp returns false instead of waiting for that prompt; no_claim=taps after the prompt answered
  it('a Desbloquear tap during a resume waits for that resume\'s prompt', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    let answerPrompt!: (ok: boolean) => void;
    mockAuthenticate.mockImplementationOnce(() => new Promise<boolean>(resolve => { answerPrompt = resolve; }));
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    let resume!: Promise<unknown[]>;
    await act(async () => { resume = Promise.all([...handlers].map(h => h('active'))); });
    const prompts = mockAuthenticate.mock.calls.length;
    let tap!: Promise<boolean>;
    let tapAnswer: boolean | null = null;
    await act(async () => { tap = authState!.unlockApp(); tap.then(ok => { tapAnswer = ok; }); });
    expect(tapAnswer).toBeNull();
    await act(async () => { answerPrompt(true); await resume; await tap; });
    nowSpy.mockRestore();
    expect(tapAnswer).toBe(true);
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(authState!.isLocked).toBe(false);
  });

  // protects=a tap that waited on a cancelled resume prompt gets "no" and leaves the button live; fails_when=the waiting tap never settles, or the next tap is still tied to the finished attempt; no_claim=taps made after the prompt answered
  it('a Desbloquear tap during a resume is told "no" when that prompt is cancelled, and the next tap prompts', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    let answerPrompt!: (ok: boolean) => void;
    mockAuthenticate.mockImplementationOnce(() => new Promise<boolean>(resolve => { answerPrompt = resolve; }));
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    let resume!: Promise<unknown[]>;
    await act(async () => { resume = Promise.all([...handlers].map(h => h('active'))); });
    let tap!: Promise<boolean>;
    let settled = false;
    await act(async () => { tap = authState!.unlockApp(); tap.then(() => { settled = true; }); });
    expect(settled).toBe(false);
    let answer = true;
    await act(async () => { answerPrompt(false); await resume; answer = await tap; });
    nowSpy.mockRestore();
    expect(answer).toBe(false);
    expect(authState!.isLocked).toBe(true);
    const prompts = mockAuthenticate.mock.calls.length;
    await act(async () => { answer = await authState!.unlockApp(); });
    expect(answer).toBe(true);
    expect(mockAuthenticate.mock.calls.length - prompts).toBe(1);
    expect(authState!.isLocked).toBe(false);
  });

  // (Pins behaviour that predates the prompt-before-refresh change.) protects=a session that ended while away is not asked for Face ID; fails_when=resume prompts before looking at the session; no_claim=the monitor's route to login (tested above)
  it('does not prompt on resume when the session is already gone', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    mockExpired = true;
    const prompts = mockAuthenticate.mock.calls.length;
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
    // The monitor, on the same return to the app, has taken it to login.
    expect(authState!.isAuthenticated).toBe(false);
    expect(authState!.isLocked).toBe(false);
  });

  // protects=a session that cannot be read right now is still locked and unlockable, not treated as gone; fails_when=an unreadable or malformed session skips the prompt or reaches the refresh; no_claim=why the keychain would fail
  it.each([
    ['unreadable', () => (Keychain.getGenericPassword as jest.Mock).mockRejectedValue(new Error('keystore busy'))],
    ['malformed', () => (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({ password: '{not json' })],
    ['missing a token', () => (Keychain.getGenericPassword as jest.Mock).mockResolvedValue({ password: JSON.stringify({ accessToken: 'access' }) })],
  ])('still asks for the unlock on resume when the session is %s, and sends no refresh', async (_name, breakSession) => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockExpired = true;
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    breakSession();
    const prompts = mockAuthenticate.mock.calls.length;
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockAuthenticate.mock.calls.length - prompts).toBe(1);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
  });

  // protects=a refresh that fails does not undo or block the unlock; fails_when=a rejected refresh re-locks, throws out of the handler or skips the uncover; no_claim=that the token gets refreshed later (the client does that per request)
  it('unlocks on a passed prompt even when the refresh is rejected', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockExpired = true;
    mockRefreshAccessToken.mockRejectedValue(new Error('offline'));
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
    expect(await Keychain.getGenericPassword()).toBeTruthy();
  });

  // protects=the stored token is brought up to date on every return to the app, not only when it locks; fails_when=the refresh moves under the lock branch; no_claim=what the refresh itself does (apollo/client)
  it('refreshes an expired token on a short return to the app, with no lock and no prompt', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockExpired = true;
    const prompts = mockAuthenticate.mock.calls.length;
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 6_000);
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(authState!.isLocked).toBe(false);
  });

  // protects=a resume that ends without a prompt hands the lock screen and sign-out back; fails_when=the resume attempt is left open when the phone's lock turns out to be no longer set up; no_claim=that reopening without a prompt is right for such a phone (decided elsewhere)
  it('reopens without a prompt when the lock is no longer set up, and leaves nothing pending', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    mockEnrolled = false;
    const prompts = mockAuthenticate.mock.calls.length;
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(authState!.isLocked).toBe(false);
    await act(async () => { await authState!.signOut(); });
    expect(Alert.alert).not.toHaveBeenCalledWith('Verificación en curso', expect.any(String));
    expect(authState!.isAuthenticated).toBe(false);
  });

  // protects=the Desbloquear button never spins without end, and never starts a second prompt beside the resume's; fails_when=a tap waits on the resume prompt without bound, or prompts on its own while that attempt is still open; no_claim=that a phone whose prompt never answers can be unlocked (it cannot: known, and as before this change)
  it('a Desbloquear tap answers "no" after ten seconds when the resume prompt never answers, without a second prompt', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    mockAuthenticate.mockImplementationOnce(() => new Promise<boolean>(() => {}));
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { [...handlers].forEach(h => { h('active'); }); });
    nowSpy.mockRestore();
    const prompts = mockAuthenticate.mock.calls.length;
    let answer: boolean | null = null;
    await act(async () => { authState!.unlockApp().then(ok => { answer = ok; }); });
    await act(async () => { jest.advanceTimersByTime(9_000); });
    expect(answer).toBeNull();
    await act(async () => { jest.advanceTimersByTime(1_000); });
    expect(answer).toBe(false);
    expect(mockAuthenticate.mock.calls.length).toBe(prompts);
    expect(authState!.isLocked).toBe(true);
  });

  // (Pins behaviour that predates the prompt-before-refresh change.) protects=a prompt that fails outright does not leave the lock screen dead; fails_when=the resume flags or the waiting tap are left hanging after a throw; no_claim=why a prompt would throw
  it('a resume prompt that throws leaves the lock up with Desbloquear live', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    let failPrompt!: (error: Error) => void;
    mockAuthenticate.mockImplementationOnce(() => new Promise<boolean>((_, reject) => { failPrompt = reject; }));
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    let resume!: Promise<unknown[]>;
    await act(async () => { resume = Promise.all([...handlers].map(h => h('active'))); });
    let tap!: Promise<boolean>;
    await act(async () => { tap = authState!.unlockApp(); });
    let answer = true;
    await act(async () => { failPrompt(new Error('keystore')); await resume; answer = await tap; });
    nowSpy.mockRestore();
    expect(answer).toBe(false);
    expect(authState!.isLocked).toBe(true);
    await act(async () => { answer = await authState!.unlockApp(); });
    expect(answer).toBe(true);
    expect(authState!.isLocked).toBe(false);
  });

  // (Pins a path that predates the 2026-11 fix.) protects=Desbloquear takes the repair path when the service says the guard is gone; fails_when=Desbloquear gives up without setting the protection up again; no_claim=how the service detects the missing guard (its own suite, where the 2026-11 iPhone 17 fix is tested)
  it('Desbloquear sets the protection up again when the service reports the guard gone', async () => {
    mockAuthenticate.mockResolvedValue(false);
    mockGuardGone = true;
    await mount();
    expect(authState!.isLocked).toBe(true);
    let unlocked = false;
    await act(async () => { unlocked = await authState!.unlockApp(); });
    await act(async () => { jest.advanceTimersByTime(100); });
    expect(mockEnable).toHaveBeenCalledTimes(1);
    expect(unlocked).toBe(true);
    expect(authState!.isLocked).toBe(false);
    expect(authState!.isAuthenticated).toBe(true);
  });

  // (Pins a path that predates the 2026-11 fix.) protects=on a resume lock (Main still mounted), Desbloquear repairs a guard the service reports gone; fails_when=the resume lock's Desbloquear gives up, or the repair drops the session or remounts; no_claim=how the service detects the missing guard (its own suite)
  it('Desbloquear repairs in place on a resume lock when the service reports the guard gone', async () => {
    const handlers = new Set<(state: string) => unknown>();
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.add(handler);
      return { remove: () => handlers.delete(handler) };
    }) as any);
    await mount();
    expect(authState!.isAuthenticated).toBe(true);
    mockAuthenticate.mockResolvedValue(false);
    mockGuardGone = true;
    const t0 = Date.now();
    const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(t0);
    await act(async () => { await Promise.all([...handlers].map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all([...handlers].map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(authState!.isLocked).toBe(true);
    expect(mockEnable).not.toHaveBeenCalled();
    let unlocked = false;
    await act(async () => { unlocked = await authState!.unlockApp(); });
    expect(mockEnable).toHaveBeenCalledTimes(1);
    expect(unlocked).toBe(true);
    expect(authState!.isLocked).toBe(false);
    expect(authenticatedStates.slice(authenticatedStates.indexOf(true))).not.toContain(false);
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

  it('routes login to device biometric setup, never Confío Face', async () => {
    await mount();
    mockClient.query.mockResolvedValue({ data: { me: { id: '1', phoneNumber: '123', phoneCountry: 'AR' } } });
    mockFace.mockClear();
    navigationRef.current.reset.mockClear();
    await act(async () => {
      await authState!.handleSuccessfulLogin(false);
    });
    // (Login queues the route; it applies once the Auth stack mounts,
    // which this already-signed-in harness never does.)
    expect(mockFace).not.toHaveBeenCalled();
  });

  it('opens the app with the device biometric at startup and on resume, never Confío Face', async () => {
    const handlers: Array<(state: string) => unknown> = [];
    jest.spyOn(AppState, 'addEventListener').mockImplementation(((_: string, handler: any) => {
      handlers.push(handler);
      return { remove: jest.fn() };
    }) as any);
    mockFace.mockClear();
    mockAuthenticate.mockClear();
    await mount();
    const nowSpy = jest.spyOn(Date, 'now');
    const t0 = Date.now();
    nowSpy.mockReturnValue(t0);
    await act(async () => { await Promise.all(handlers.map(h => h('background'))); });
    nowSpy.mockReturnValue(t0 + 60_000);
    await act(async () => { await Promise.all(handlers.map(h => h('active'))); });
    nowSpy.mockRestore();
    expect(mockAuthenticate).toHaveBeenCalledWith('Desbloquea Confío');
    expect(mockFace).not.toHaveBeenCalled();
    expect(authState!.isLocked).toBe(false);
  });
});
