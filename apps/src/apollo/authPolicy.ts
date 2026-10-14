const PUBLIC_AUTH_OPERATIONS = new Set([
  'RefreshToken',
  'Web3AuthLogin',
]);

/**
 * Operations that establish or renew a Confío session must not inherit the
 * session already stored on the device. That JWT may belong to a deleted or
 * invalidated user, and attaching it can prevent the fresh identity proof
 * from ever reaching the public authentication resolver.
 */
export function shouldSkipStoredJwt(
  operationName: string | undefined,
  explicitlySkipped: boolean = false,
): boolean {
  return explicitlySkipped || PUBLIC_AUTH_OPERATIONS.has(operationName || '');
}

/**
 * Operations that must never change the stored session as a side effect.
 *
 * Wallet-recovery telemetry runs DURING a failing sign-in, on whatever token
 * happens to be in Keychain. Letting it refresh that token, or clear the
 * session when the server rejects it, moves authentication state underneath
 * the recovery the user is waiting on — the report is best effort, the
 * session is not. Losing the report is the correct trade.
 */
const SESSION_READ_ONLY_OPERATIONS = new Set([
  'ReportWalletRecoveryDiagnostic',
]);

export function shouldNeverMutateSession(operationName: string | undefined): boolean {
  return SESSION_READ_ONLY_OPERATIONS.has(operationName || '');
}
