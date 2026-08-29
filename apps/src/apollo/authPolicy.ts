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
