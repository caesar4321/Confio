import {
  assertMatchingGoogleAccount,
  driveSupportCode,
  GoogleDriveAccountMismatchError,
  GoogleDriveReauthorizationCancelledError,
  isDriveAuthorizationFailure,
  runWithDriveAuthorizationRetry,
} from '../googleDriveAuthPolicy';

describe('googleDriveAuthPolicy', () => {
  it('only retries authorization failures returned by Google Drive storage', () => {
    expect(isDriveAuthorizationFailure({ name: 'GoogleDriveStorageError', status: 401 })).toBe(true);
    expect(isDriveAuthorizationFailure({ name: 'GoogleDriveStorageError', status: 403 })).toBe(true);
    expect(isDriveAuthorizationFailure({
      name: 'GoogleDriveStorageError',
      status: 403,
      reason: 'storageQuotaExceeded',
    })).toBe(false);
    expect(isDriveAuthorizationFailure({
      name: 'GoogleDriveStorageError',
      status: 403,
      reason: 'accessNotConfigured',
    })).toBe(false);
    expect(isDriveAuthorizationFailure({
      name: 'GoogleDriveStorageError',
      status: 403,
      reason: 'domainPolicy',
    })).toBe(false);
    expect(isDriveAuthorizationFailure({ name: 'ApolloError', status: 401 })).toBe(false);
    expect(isDriveAuthorizationFailure({ name: 'GoogleDriveStorageError', status: 429 })).toBe(false);
  });

  it('rejects a Drive account that differs from the logged-in Google identity', () => {
    expect(() => assertMatchingGoogleAccount('google-subject-a', 'google-subject-b'))
      .toThrow(GoogleDriveAccountMismatchError);
    expect(() => assertMatchingGoogleAccount('google-subject-a', 'google-subject-a'))
      .not.toThrow();
  });

  it('only exposes bounded support codes', () => {
    expect(driveSupportCode({ supportCode: 'DRIVE-403-INSUFFICIENTPERMISSIONS' }))
      .toBe('DRIVE-403-INSUFFICIENTPERMISSIONS');
    expect(driveSupportCode({ supportCode: 'google said: user@example.com' }))
      .toBeUndefined();
  });

  it('reauthorizes and retries a rejected Drive operation exactly once', async () => {
    const operation = jest.fn()
      .mockRejectedValueOnce(Object.assign(new Error('rejected'), {
        name: 'GoogleDriveStorageError',
        status: 403,
        supportCode: 'DRIVE-403-AUTHERROR',
      }))
      .mockResolvedValueOnce('synced');
    const reauthorize = jest.fn().mockResolvedValue('fresh-token');

    await expect(runWithDriveAuthorizationRetry('stale-token', operation, reauthorize))
      .resolves.toBe('synced');
    expect(operation).toHaveBeenNthCalledWith(1, 'stale-token');
    expect(operation).toHaveBeenNthCalledWith(2, 'fresh-token');
    expect(reauthorize).toHaveBeenCalledTimes(1);
  });

  it('does not loop when the fresh Drive token is also rejected', async () => {
    const rejected = Object.assign(new Error('rejected'), {
      name: 'GoogleDriveStorageError',
      status: 403,
    });
    const operation = jest.fn().mockRejectedValue(rejected);

    await expect(runWithDriveAuthorizationRetry(
      'stale-token',
      operation,
      async () => 'fresh-token',
    )).rejects.toBe(rejected);
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it('preserves the original safe support code when reauthorization is cancelled', async () => {
    const rejected = Object.assign(new Error('rejected'), {
      name: 'GoogleDriveStorageError',
      status: 401,
      supportCode: 'DRIVE-401-AUTHERROR',
    });

    await expect(runWithDriveAuthorizationRetry(
      'stale-token',
      async () => { throw rejected; },
      async () => null,
    )).rejects.toMatchObject<GoogleDriveReauthorizationCancelledError>({
      name: 'GoogleDriveReauthorizationCancelledError',
      supportCode: 'DRIVE-401-AUTHERROR',
    });
  });
});
