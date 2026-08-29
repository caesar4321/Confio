export type DriveAuthorizationFailure = {
  name?: string;
  status?: number;
  reason?: string | null;
  supportCode?: string;
};

export class GoogleDriveAccountMismatchError extends Error {
  supportCode = 'DRIVE-ACCOUNT-MISMATCH';

  constructor() {
    super('Seleccionaste una cuenta de Google diferente a la que usaste para entrar en Confío.');
    this.name = 'GoogleDriveAccountMismatchError';
  }
}

export class GoogleDriveScopeMissingError extends Error {
  supportCode = 'DRIVE-SCOPE-MISSING';

  constructor() {
    super('Google no concedió el permiso necesario para guardar el respaldo en Drive.');
    this.name = 'GoogleDriveScopeMissingError';
  }
}

export class GoogleDriveReauthorizationCancelledError extends Error {
  supportCode: string;

  constructor(supportCode?: string) {
    super('No se pudo renovar el acceso a Google Drive.');
    this.name = 'GoogleDriveReauthorizationCancelledError';
    this.supportCode = supportCode || 'DRIVE-REAUTH-CANCELLED';
  }
}

const NON_REAUTHORIZABLE_DRIVE_REASONS = new Set([
  'accessNotConfigured',
  'dailyLimitExceeded',
  'domainPolicy',
  'storageQuotaExceeded',
  'userRateLimitExceeded',
]);

export const isDriveAuthorizationFailure = (error: DriveAuthorizationFailure | null | undefined): boolean => {
  if (error?.name !== 'GoogleDriveStorageError') return false;
  if (error.status === 401) return true;
  return error.status === 403 && !NON_REAUTHORIZABLE_DRIVE_REASONS.has(error.reason || '');
};

export const driveSupportCode = (error: DriveAuthorizationFailure | null | undefined): string | undefined => {
  if (typeof error?.supportCode !== 'string') return undefined;
  return /^DRIVE-[A-Z0-9_-]{1,96}$/.test(error.supportCode)
    ? error.supportCode
    : undefined;
};

export const assertMatchingGoogleAccount = (
  expectedGoogleSubject: string | undefined,
  selectedGoogleSubject: string | null | undefined,
): void => {
  if (!expectedGoogleSubject) return;
  if (!selectedGoogleSubject || selectedGoogleSubject !== expectedGoogleSubject) {
    throw new GoogleDriveAccountMismatchError();
  }
};

export const runWithDriveAuthorizationRetry = async <T>(
  initialAccessToken: string,
  operation: (accessToken: string) => Promise<T>,
  reauthorize: (rejectedError: DriveAuthorizationFailure) => Promise<string | null>,
): Promise<T> => {
  try {
    return await operation(initialAccessToken);
  } catch (error: any) {
    if (!isDriveAuthorizationFailure(error)) throw error;

    const freshAccessToken = await reauthorize(error);
    if (!freshAccessToken) {
      throw new GoogleDriveReauthorizationCancelledError(driveSupportCode(error));
    }

    // Deliberately no second catch/retry: one fresh authorization is enough
    // to distinguish a stale token from a persistent policy/configuration
    // rejection without trapping the user in repeated account prompts.
    return operation(freshAccessToken);
  }
};
