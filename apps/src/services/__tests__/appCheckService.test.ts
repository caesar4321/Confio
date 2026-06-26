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
        nowSpy.mockReturnValueOnce(1_000);
        mockGetToken
            .mockRejectedValueOnce(new Error('Error returned from API. code: 403 body: App attestation failed.'))
            .mockRejectedValueOnce(new Error('Too many attempts.'));

        const service = new AppCheckService();
        await service.getTokenForHeader();
        nowSpy.mockReturnValue(32_000);
        await service.getTokenForHeader();

        expect(service.getAuthFailureMessage()).toContain('Play Protect certifique tu dispositivo');
    });
});
