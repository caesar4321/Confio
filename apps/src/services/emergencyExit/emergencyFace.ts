// The ban route of the emergency exit (security/emergency_exit.py).
//
// A banned account cannot use GraphQL (the security middleware 403s every
// authenticated request), so this talks to plain endpoints with no JWT and
// proves the account by signing a one-time challenge with the account's own
// BSC key. The server then says whether the account is really banned — a
// faked 403 cannot route a healthy account here — and, if so, the exit runs
// only after Confío Face passes, with no waiting-period fallback. A banned
// account that never did KYC has no face to check and gets the normal
// waiting period instead. Every call carries an App Check token (Play
// Integrity / App Attest).

import type { DerivedEvmWallet } from '../evmWallet';
import { mobileClientHeaders } from '../mobileClientHeaders';
import type { FaceCheckBackend, FaceCheckGrade, FaceCheckStart } from '../faceStepUp';

export type BannedExitOutcome =
  /** Face passed, or the server does not ask for one: the exit may run. */
  | { outcome: 'passed'; faceChecked: boolean }
  /** The server says this account is not banned: use the normal route. */
  | { outcome: 'not_banned' }
  /** Banned with no KYC selfie to compare against: the normal waiting period applies. */
  | { outcome: 'wait' }
  | { outcome: 'failed'; message: string };

export interface BannedExitDeps {
  fetchImpl?: typeof fetch;
  getAppCheckToken?: () => Promise<string | null>;
  sign?: (message: string, privKeyHex: string) => string;
  presentFace?: (backend: FaceCheckBackend) => Promise<boolean>;
}

const REQUEST_TIMEOUT_MS = 15000;
const NETWORK_MESSAGE = 'No pudimos conectar con Confío. Revisa tu conexión e intenta de nuevo.';
const FACE_FAILED_MESSAGE =
  'Tu cuenta está suspendida: para usar la salida de emergencia necesitas confirmar con tu rostro que eres tú.';

/** 'https://confio.lat/graphql/' → 'https://confio.lat' */
export const apiOrigin = (graphqlUrl: string): string => graphqlUrl.replace(/\/graphql\/?$/, '');

const defaultAppCheckToken = async (): Promise<string | null> => {
  try {
    const { appCheckService } = await import('../appCheckService');
    // The server enforces App Check on these calls: wait for a real token
    // rather than the cached-or-null header value.
    return await appCheckService.waitForToken();
  } catch {
    return null;
  }
};

const defaultSign = (message: string, privKeyHex: string): string =>
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  require('../evmWallet').signEip191Message(message, privKeyHex);

const defaultPresentFace = async (backend: FaceCheckBackend): Promise<boolean> => {
  const { ensureFaceCheck } = await import('../faceStepUp');
  return ensureFaceCheck('emergency_exit', backend);
};

export const confirmBannedExit = async (
  wallet: DerivedEvmWallet,
  graphqlUrl: string,
  deps: BannedExitDeps = {},
): Promise<BannedExitOutcome> => {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const getAppCheckToken = deps.getAppCheckToken ?? defaultAppCheckToken;
  const origin = apiOrigin(graphqlUrl);

  // Never an Authorization header: the middleware would 403 a banned user.
  const post = async (path: string, body: object, withAppCheck = false): Promise<any> => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...mobileClientHeaders() };
    if (withAppCheck) {
      const token = await getAppCheckToken();
      if (token) headers['X-Firebase-AppCheck'] = token;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetchImpl(`${origin}${path}`, {
        method: 'POST', headers, body: JSON.stringify(body), signal: ctrl.signal,
      });
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  };

  let session: any;
  try {
    const address = wallet.address.toLowerCase();
    const challenge = await post('/api/emergency-exit/challenge/', { address });
    if (!challenge?.success) return { outcome: 'failed', message: challenge?.error || NETWORK_MESSAGE };
    const signature = (deps.sign ?? defaultSign)(challenge.message, wallet.privKeyHex);
    session = await post('/api/emergency-exit/session/', { address, nonce: challenge.nonce, signature }, true);
  } catch {
    return { outcome: 'failed', message: NETWORK_MESSAGE };
  }
  if (!session?.success) return { outcome: 'failed', message: session?.error || NETWORK_MESSAGE };
  if (!session.banned) return { outcome: 'not_banned' };
  if (session.waitRequired) return { outcome: 'wait' };
  if (!session.faceRequired) return { outcome: 'passed', faceChecked: false };

  const backend: FaceCheckBackend = {
    start: async (): Promise<FaceCheckStart> =>
      post('/api/emergency-exit/face/start/', { token: session.token }, true),
    complete: async (sessionId: string): Promise<FaceCheckGrade> =>
      post('/api/emergency-exit/face/complete/', { token: session.token, sessionId }, true),
  };
  const passed = await (deps.presentFace ?? defaultPresentFace)(backend);
  return passed ? { outcome: 'passed', faceChecked: true } : { outcome: 'failed', message: FACE_FAILED_MESSAGE };
};
