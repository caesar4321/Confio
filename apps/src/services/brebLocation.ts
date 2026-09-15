import {NativeModules, PermissionsAndroid, Platform} from 'react-native';
import {gql} from '@apollo/client';

const CHALLENGE = gql`mutation BrebLocationChallenge($platform: String, $keyId: String) {
  brebLocationChallenge(platform: $platform, keyId: $keyId) { success challenge cloudProjectNumber keyRegistered error }
}`;
const APPLY = gql`mutation ApplyCobreBreb($challenge: String!, $locationJson: String!, $integrityToken: String!) {
  applyCobreBreb(challenge: $challenge, locationJson: $locationJson, integrityToken: $integrityToken) {
    success value validUntil error
  }
}`;

const VERIFY = gql`mutation VerifyBrebLocation($challenge: String!, $locationJson: String!, $integrityToken: String!) {
  verifyBrebLocation(challenge: $challenge, locationJson: $locationJson, integrityToken: $integrityToken) {
    success validUntil error
  }
}`;

/** Error code of a refused system location permission (the only case that
 * sends the person to Settings; anything later is a plain retry). */
export const BREB_PERMISSION_ERROR = 'BREB_LOCATION_PERMISSION';

// Every location request has a deadline: a stalled one must release the
// screen with a retryable error, never keep it loading. A late answer is ignored.
const REQUEST_TIMEOUT_MS = 20000;
const APPLY_TIMEOUT_MS = 45000;
function withinTime<T>(promise: Promise<T>, ms = REQUEST_TIMEOUT_MS): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('La verificación tardó demasiado. Intenta de nuevo.')), ms);
    promise.then(
      value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); },
    );
  });
}

async function collectEvidence(requestPermission = false) {
  if (!brebLocationSupported()) {
    throw new Error('Actualiza Confío para usar Bre-B.');
  }
  // Only the location screen's explicit action may open the system prompt.
  // Automatic retries and applications must use an existing permission.
  const permission = requestPermission
    ? await requestBrebLocationPermission()
    : await hasBrebLocationPermission() ? 'granted' : 'denied';
  if (permission !== 'granted') {
    const refused: Error & {code?: string} = new Error(permission === 'reduced'
      ? 'Activa la ubicación precisa para usar Bre-B.'
      : 'Permite la ubicación precisa para usar Bre-B. Si la negaste, actívala en Ajustes.');
    refused.code = BREB_PERMISSION_ERROR;
    throw refused;
  }
  const {apolloClient} = await import('../apollo/client');
  const keyId = Platform.OS === 'ios' ? await NativeModules.BrebAppleLocation.keyId() : '';
  const response = await withinTime(apolloClient.mutate({mutation: CHALLENGE, variables: {platform: Platform.OS, keyId}}));
  const challenge = response.data?.brebLocationChallenge;
  if (!challenge?.success || !challenge.challenge) throw new Error(challenge?.error || 'No pudimos iniciar la verificación.');
  if (Platform.OS === 'android' && !/^[1-9][0-9]{0,18}$/.test(challenge.cloudProjectNumber || '')) throw new Error('La verificación del dispositivo aún no está disponible.');
  const evidence = Platform.OS === 'ios'
    ? await NativeModules.BrebAppleLocation.attest(challenge.challenge, challenge.keyRegistered === true)
    : await NativeModules.BrebLocation.attest(challenge.challenge, challenge.cloudProjectNumber);
  return {challenge: challenge.challenge, locationJson: evidence.locationJson, integrityToken: evidence.integrityToken};
}

export async function applyCobreBreb(scope = ''): Promise<string> {
  const variables = await collectEvidence();
  const {apolloClient} = await import('../apollo/client');
  const result = await withinTime(apolloClient.mutate({mutation: APPLY, variables}), APPLY_TIMEOUT_MS);
  const application = result.data?.applyCobreBreb;
  if (!application?.success || !application.value) throw new Error(application?.error || 'Tu llave aún no está disponible.');
  // The application's reading is also a location pass; the key shows while it lasts.
  rememberPass(scope, Number(application.validUntil));
  return application.value;
}

/** Retry only an explicit pre-operation location refusal, never a timeout or
 * ambiguous financial failure. Server rechecks owner, IP and pass on retry. */
export async function withBrebLocationRetry<T extends {success?: boolean; errors?: string[]}>(operation: () => Promise<T>): Promise<T> {
  const result = await operation();
  if (result?.success !== false || result.errors?.[0] !== 'Verifica tu ubicación para usar Bre-B.') return result;
  // The server no longer accepts the cached pass: forget it, so no screen trusts it.
  const scope = passScope; // whose pass this was, to restore after a new check
  passUntil = 0;
  notifyPass();
  try {
    const variables = await collectEvidence();
    const {apolloClient} = await import('../apollo/client');
    const response = await withinTime(apolloClient.mutate({mutation: VERIFY, variables}));
    const verification = response.data?.verifyBrebLocation;
    if (!verification?.success) throw new Error(verification?.error || 'No pudimos verificar tu ubicación.');
    // The new check is that account's pass again, unless another check (e.g.
    // after switching accounts) replaced it meanwhile.
    if (passScope === scope) rememberPass(scope, Number(verification.validUntil));
  } catch (error: any) {
    // The location step failed, not the operation: its message (and a refused
    // permission's code) is kept, so a screen can offer the location screen.
    throw Object.assign(error instanceof Error ? error : new Error(String(error)), {brebLocation: true});
  }
  const retried = await operation();
  if (retried?.success === false && retried.errors?.[0] === 'Verifica tu ubicación para usar Bre-B.') {
    // Refused again right after a new check (e.g. the network or IP changed):
    // that pass is not accepted either. Forget it and hand the screen a
    // location failure to recover from, never another automatic retry.
    passUntil = 0;
    notifyPass();
    throw Object.assign(new Error('Verifica tu ubicación para usar Bre-B.'), {brebLocation: true});
  }
  return retried;
}

export {isBrebLocationFailure} from './brebLocationFailure';

// ─── Bre-B screens (UI) ───
// The server is the authority on the pass; this only avoids re-checking a
// screen that was verified moments ago.
let passUntil = 0;
let passScope = '';

export const brebLocationSupported = (): boolean => Platform.OS === 'android' ? Boolean(NativeModules.BrebLocation)
  : Platform.OS === 'ios' && Number.parseInt(String(Platform.Version), 10) >= 15 && Boolean(NativeModules.BrebAppleLocation);

export type BrebLocationPermission = 'granted' | 'reduced' | 'denied' | 'blocked';

/** Shows the system location prompt when it has not been answered yet. */
export async function requestBrebLocationPermission(): Promise<BrebLocationPermission> {
  if (Platform.OS === 'android') {
    const permissions = await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
      PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION,
    ]);
    const fine = permissions[PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION];
    if (fine === PermissionsAndroid.RESULTS.GRANTED) return 'granted';
    if (permissions[PermissionsAndroid.PERMISSIONS.ACCESS_COARSE_LOCATION] === PermissionsAndroid.RESULTS.GRANTED) {
      return 'reduced'; // approximate only
    }
    return fine === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN ? 'blocked' : 'denied';
  }
  // iOS: the native module prompts and answers after the person decides. A
  // build without it still prompts inside attest().
  const request = NativeModules.BrebAppleLocation?.requestPermission;
  if (typeof request !== 'function') return 'granted';
  const state = String(await request());
  return state === 'granted' || state === 'reduced' ? state : 'denied';
}

/** Precise location already allowed: a screen can check silently, no prompt. */
export async function hasBrebLocationPermission(): Promise<boolean> {
  if (!brebLocationSupported()) return false;
  if (Platform.OS === 'android') {
    return PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
  }
  // iOS: the native module reports its authorization when it can; otherwise
  // the permission screen shows and the module prompts on "Permitir".
  const check = NativeModules.BrebAppleLocation.hasPermission;
  return typeof check === 'function' ? Boolean(await check()) : false;
}

export const brebLocationPassValid = (scope: string): boolean => Boolean(scope) && passScope === scope && passUntil * 1000 > Date.now() + 30000;

/** Milliseconds until this scope's pass stops counting as valid (0 when it already has). */
export const brebLocationPassRemainingMs = (scope: string): number =>
  brebLocationPassValid(scope) ? passUntil * 1000 - Date.now() - 30000 : 0;

function rememberPass(scope: string, expiry: number) {
  if (scope && Number.isFinite(expiry) && expiry * 1000 > Date.now()) {
    passScope = scope;
    passUntil = expiry;
    notifyPass();
  }
}

const passListeners = new Set<() => void>();
/** Screens that show a key follow every change of the pass (granted, renewed, forgotten). */
export function onBrebLocationPassChange(listener: () => void): () => void {
  passListeners.add(listener);
  return () => { passListeners.delete(listener); };
}
function notifyPass() {
  passListeners.forEach(listener => {
    try { listener(); } catch { /* one screen's failure never blocks another */ }
  });
}

/** A Bre-B screen's explicit check (asks for permission when missing). */
export async function verifyBrebLocation(scope = '', requestPermission = true): Promise<number> {
  const variables = await collectEvidence(requestPermission);
  const {apolloClient} = await import('../apollo/client');
  const response = await withinTime(apolloClient.mutate({mutation: VERIFY, variables}));
  const verification = response.data?.verifyBrebLocation;
  const expiry = Number(verification?.validUntil);
  if (!verification?.success || !Number.isFinite(expiry) || expiry * 1000 <= Date.now()) {
    throw new Error(verification?.error || 'No pudimos verificar tu ubicación.');
  }
  passScope = scope;
  passUntil = expiry;
  notifyPass();
  return passUntil;
}
