const mockGetToken = jest.fn();
const mockInitializeAppCheck = jest.fn();
const mockConfigure = jest.fn();

jest.mock('@env', () => ({
    ALLOW_APP_CHECK_DEBUG: 'false',
    FIREBASE_APP_CHECK_DEBUG_TOKEN_ANDROID: '',
    FIREBASE_APP_CHECK_DEBUG_TOKEN_IOS: '',
}), { virtual: true });

jest.mock('@react-native-firebase/app-check', () => ({
    __esModule: true,
    default: () => ({
        getToken: mockGetToken,
        initializeAppCheck: mockInitializeAppCheck,
        newReactNativeFirebaseAppCheckProvider: () => ({ configure: mockConfigure }),
    }),
}));

import { AppCheckService } from '../appCheckService';
import { Platform } from 'react-native';

describe('AppCheckService', () => {
    beforeAll(() => {
        Object.defineProperty(Platform, 'OS', { value: 'android' });
    });

    beforeEach(() => {
        jest.clearAllMocks();
        mockInitializeAppCheck.mockResolvedValue(undefined);
    });

    it('makes one auth-only retry after a cached transient startup failure', async () => {
        mockGetToken
            .mockRejectedValueOnce(new Error('Network request failed'))
            .mockResolvedValueOnce({ token: 'valid-app-check-token' });

        const service = new AppCheckService();

        await expect(service.getTokenForHeader()).resolves.toBeNull();
        await expect(service.primeTokenForAuth()).resolves.toBe('valid-app-check-token');
        expect(mockGetToken).toHaveBeenNthCalledWith(1, false);
        expect(mockGetToken).toHaveBeenNthCalledWith(2, true);
    });

    it('does not immediately retry an attestation rejection', async () => {
        mockGetToken.mockRejectedValue(new Error('Error returned from API. code: 403 body: App attestation failed.'));

        const service = new AppCheckService();

        await expect(service.getTokenForHeader()).resolves.toBeNull();
        await expect(service.primeTokenForAuth()).resolves.toBeNull();
        expect(mockGetToken).toHaveBeenCalledTimes(1);
    });

    it('keeps attestation guidance when Firebase later reports native backoff', async () => {
        const nowSpy = jest.spyOn(Date, 'now');
        nowSpy.mockReturnValue(1_000);
        mockGetToken
            .mockRejectedValueOnce(new Error('Error returned from API. code: 403 body: App attestation failed.'))
            .mockRejectedValueOnce(new Error('Too many attempts.'));

        const service = new AppCheckService();
        await service.waitForToken();
        // Jump past the fetch cooldown and failure backoff so the second
        // fetch really fires and records the native backoff error.
        nowSpy.mockReturnValue(32_000);
        await service.waitForToken();

        expect(mockGetToken).toHaveBeenCalledTimes(2);
        expect(service.getAuthFailureMessage()).toContain('Play Protect certifique tu dispositivo');
        nowSpy.mockRestore();
    });
});

/**
 * Pins the split token semantics that keep the app responsive on networks
 * where the native Firebase token exchange stalls (e.g. hotspots that
 * advertise IPv6 but black-hole it, ~2 min of TCP retries per connect):
 * - getTokenForHeader() must never await an in-flight fetch (best-effort header)
 * - waitForToken() must await the real result (backend-enforced operations)
 */
describe('AppCheckService token fetch semantics', () => {
    beforeEach(() => {
        // Full reset (not just clear): earlier tests may leave once-queued
        // rejections on mockGetToken or a Date.now spy behind.
        jest.restoreAllMocks();
        mockGetToken.mockReset();
        mockConfigure.mockReset();
        mockInitializeAppCheck.mockReset();
        mockInitializeAppCheck.mockResolvedValue(undefined);
    });

    function deferred<T>() {
        let resolve!: (value: T) => void;
        const promise = new Promise<T>((res) => {
            resolve = res;
        });
        return { promise, resolve };
    }

    it('getTokenForHeader resolves immediately while a fetch is in flight', async () => {
        const pending = deferred<{ token: string }>();
        mockGetToken.mockReturnValue(pending.promise);

        const service = new AppCheckService();
        const inFlight = service.waitForToken();

        // Must resolve without waiting for the native fetch: null, since
        // nothing is cached yet. Awaiting the pending fetch would time out.
        await expect(service.getTokenForHeader()).resolves.toBeNull();

        pending.resolve({ token: 'fresh-token' });
        await expect(inFlight).resolves.toBe('fresh-token');
    });

    it('getTokenForHeader returns the cached token without refetching', async () => {
        mockGetToken.mockResolvedValue({ token: 'cached-token' });

        const service = new AppCheckService();
        await service.waitForToken();

        mockGetToken.mockClear();
        await expect(service.getTokenForHeader()).resolves.toBe('cached-token');
        expect(mockGetToken).not.toHaveBeenCalled();
    });

    it('waitForToken shares the in-flight fetch and returns its result', async () => {
        const pending = deferred<{ token: string }>();
        mockGetToken.mockReturnValue(pending.promise);

        const service = new AppCheckService();
        const first = service.waitForToken();
        const second = service.waitForToken();

        pending.resolve({ token: 'shared-token' });
        await expect(first).resolves.toBe('shared-token');
        await expect(second).resolves.toBe('shared-token');
        expect(mockGetToken).toHaveBeenCalledTimes(1);
    });
});
