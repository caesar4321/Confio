/**
 * Confío Face — prove it's you before money moves.
 *
 * The server asks for a face step-up (next_step 'face_check', or the exact
 * FACE_STEP_UP_MESSAGE) before a deposit order, a withdrawal, or a send to an
 * external address. We open an AWS Face Liveness capture with short-lived
 * credentials limited to streaming liveness video. The server binds the
 * session to this user, grades it against the KYC selfie, and returns pass/fail.
 *
 * Service code (sends, journeys) runs outside React, so the modal host
 * (FaceCheckProvider) registers a presenter here and callers use
 * `ensureFaceCheck` / `withFaceStepUp`.
 */
import { gql } from '@apollo/client';
import { NativeModules } from 'react-native';

// Money movements only. Opening the app uses the phone's own biometric
// ('app_unlock' remains a server purpose for older builds and history).
export type FaceCheckPurpose = 'on_ramp' | 'withdrawal' | 'emergency_exit' | 'payin_release' | 'payroll_authority';
export type FaceCaptureOutcome = 'passed' | 'failed' | 'cancelled' | 'unavailable';

// Mirrors security/face_step_up.py. The server sends this exact text when a
// step-up is required on paths that have no nextStep field.
export const FACE_STEP_UP_MESSAGE = 'Confirma que eres tú con tu rostro para continuar.';
export const FACE_STEP_UP_NEXT_STEP = 'face_check';
const PENDING_MESSAGE = 'Todavía estamos procesando tu verificación. Intenta de nuevo en unos segundos.';

const START = gql`
  mutation StartFaceCheck($purpose: String!) {
    startFaceCheck(purpose: $purpose) {
      success
      error
      sessionId
      region
      accessKeyId
      secretAccessKey
      sessionToken
      expiration
    }
  }
`;

// With the movement the check is for, so a small one inside Confío gets the
// light challenge (no colour lights). Its own document: a server without
// these arguments rejects it, and the plain START is used instead.
const START_FOR_MOVEMENT = gql`
  mutation StartFaceCheckForMovement($purpose: String!, $amount: String!, $tokenType: String!, $leavesConfio: Boolean!) {
    startFaceCheck(purpose: $purpose, amount: $amount, tokenType: $tokenType, leavesConfio: $leavesConfio) {
      success
      error
      sessionId
      region
      accessKeyId
      secretAccessKey
      sessionToken
      expiration
    }
  }
`;

const COMPLETE = gql`
  mutation CompleteFaceCheck($sessionId: String!) {
    completeFaceCheck(sessionId: $sessionId) {
      success
      passed
      error
    }
  }
`;

// Its own operation (never merged into a shared query): an older server
// without this field must fail only this call, not a whole screen query.
const STATUS = gql`
  query FaceStepUpStatus {
    faceStepUpStatus {
      enabled
      available
      required
    }
  }
`;

/**
 * Whether the server enforces Confío Face, and whether it asks it of this
 * user (only people who went through KYC); null when it cannot be read.
 */
export const fetchFaceStepUpStatus = async (): Promise<{ enabled: boolean; required: boolean | null } | null> => {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await withTimeout(apolloClient.query({ query: STATUS, fetchPolicy: 'network-only' }), 15000);
    const status = data?.faceStepUpStatus;
    return status
      ? { enabled: !!status.enabled, required: typeof status.required === 'boolean' ? status.required : null }
      : null;
  } catch {
    return null;
  }
};

export class FaceCheckError extends Error {
  constructor(public outcome: FaceCaptureOutcome, message: string) {
    super(message);
  }
}

export const isFaceStepUpRequired = (errorOrNextStep?: string | null): boolean =>
  errorOrNextStep === FACE_STEP_UP_NEXT_STEP || errorOrNextStep === FACE_STEP_UP_MESSAGE;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// A hung request must never leave the Confío Face modal spinning.
const START_TIMEOUT_MS = 20000;
const COMPLETE_TIMEOUT_MS = 15000;
const CAMERA_DENIED_MESSAGE =
  'Confío necesita acceso a la cámara para confirmar que eres tú. Actívalo en los ajustes de tu teléfono.';

// Ours (the native modules), and the AWS view's own on Android.
const CAMERA_DENIED_CODES = new Set(['camera_permission_denied', 'CameraPermissionDeniedException']);

const withTimeout = <T>(promise: Promise<T>, ms: number): Promise<T> =>
  new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(
      value => { clearTimeout(timer); resolve(value); },
      error => { clearTimeout(timer); reject(error); },
    );
  });

/** What the start call returns (the startFaceCheck mutation's fields). */
export interface FaceCheckStart {
  success: boolean;
  error?: string | null;
  sessionId?: string;
  region?: string;
  accessKeyId?: string;
  secretAccessKey?: string;
  sessionToken?: string;
  expiration?: string;
}

export interface FaceCheckGrade {
  success: boolean;
  passed: boolean;
  error?: string | null;
}

/**
 * Where a face check is opened and graded. GraphQL for signed-in users; the
 * banned-account emergency exit has its own wallet-signed endpoints
 * (emergencyExit/emergencyFace.ts), since a banned user cannot use GraphQL.
 */
export interface FaceCheckBackend {
  start(purpose: FaceCheckPurpose): Promise<FaceCheckStart | undefined>;
  complete(sessionId: string): Promise<FaceCheckGrade | undefined>;
}

/**
 * The server records the App Check verdict (Play Integrity / App Attest) of
 * every face check. The GraphQL link only attaches a token already cached,
 * so fetch one first; a failure just means the check is recorded without one.
 */
const primeAppCheck = async (): Promise<void> => {
  try {
    const { appCheckService } = await import('./appCheckService');
    await appCheckService.waitForToken();
  } catch { /* recorded as missing; never blocks the check */ }
};

/**
 * What a withdrawal-purpose check is about to approve. Only a hint for which
 * challenge to run: the server spends the check against its own terms, so an
 * understated movement just gets a check that cannot approve it.
 */
export interface FaceCheckMovement {
  amount: string | number;
  /** e.g. 'cUSD', 'USDT', 'CONFIO' (only dollar tokens can get the light challenge). */
  tokenType: string;
  /** True when the money leaves Confío (external address, bank). */
  leavesConfio: boolean;
}

const graphqlBackend: FaceCheckBackend = {
  async start(purpose) {
    await primeAppCheck();
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({ mutation: START, variables: { purpose } });
    return data?.startFaceCheck;
  },
  async complete(sessionId) {
    await primeAppCheck();
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({ mutation: COMPLETE, variables: { sessionId } });
    return data?.completeFaceCheck;
  },
};

/**
 * The GraphQL backend, opening the session with the movement it is for.
 * The same movement returns the same backend object: FaceCheckProvider joins
 * a second request to the open check only when its backend is identical.
 */
let lastMovement: { key: string; backend: FaceCheckBackend } | null = null;
export const movementBackend = (movement: FaceCheckMovement): FaceCheckBackend => {
  const key = JSON.stringify([String(movement.amount), movement.tokenType, movement.leavesConfio]);
  if (lastMovement?.key !== key) lastMovement = { key, backend: buildMovementBackend(movement) };
  return lastMovement.backend;
};

const buildMovementBackend = (movement: FaceCheckMovement): FaceCheckBackend => ({
  async start(purpose) {
    await primeAppCheck();
    const { apolloClient } = await import('../apollo/client');
    try {
      const { data } = await apolloClient.mutate({
        mutation: START_FOR_MOVEMENT,
        variables: {
          purpose,
          amount: String(movement.amount),
          tokenType: movement.tokenType,
          leavesConfio: movement.leavesConfio,
        },
      });
      if (data?.startFaceCheck) return data.startFaceCheck;
    } catch {
      // Older server without the movement arguments: a full check still works.
    }
    const { data } = await apolloClient.mutate({ mutation: START, variables: { purpose } });
    return data?.startFaceCheck;
  },
  complete: graphqlBackend.complete,
});

/** Server session → native capture → server grade. Never throws. */
export const runFaceCapture = async (
  purpose: FaceCheckPurpose,
  onGrading?: () => void,
  backend: FaceCheckBackend = graphqlBackend,
): Promise<{ outcome: FaceCaptureOutcome; message?: string }> => {
  const native = NativeModules.ConfioFaceLiveness;
  if (!native?.start) {
    return { outcome: 'unavailable', message: 'Actualiza Confío para confirmar tu identidad.' };
  }
  let start: FaceCheckStart | undefined;
  try {
    start = await withTimeout(backend.start(purpose), START_TIMEOUT_MS);
  } catch {
    return { outcome: 'unavailable', message: 'Revisa tu conexión e intenta de nuevo.' };
  }
  if (!start?.success || !start.sessionId || !start.expiration) {
    return { outcome: 'unavailable', message: start?.error || 'No pudimos iniciar la verificación.' };
  }
  const sessionId = start.sessionId;
  nativeCaptures += 1;
  try {
    await native.start(sessionId, start.region, {
      accessKeyId: start.accessKeyId,
      secretAccessKey: start.secretAccessKey,
      sessionToken: start.sessionToken,
      expirationEpochSeconds: Math.floor(Date.parse(start.expiration) / 1000),
    });
  } catch (error: any) {
    if (error?.code === 'UserCancelledException') return { outcome: 'cancelled' };
    if (CAMERA_DENIED_CODES.has(error?.code)) return { outcome: 'unavailable', message: CAMERA_DENIED_MESSAGE };
    // A capture error still lets the server record the session as failed.
  } finally {
    nativeCaptures -= 1;
    lastCaptureEndedAt = Date.now();
  }
  onGrading?.();
  // AWS may still be processing the video: the server answers PENDING_MESSAGE
  // and the same call is safe to repeat.
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const result = await withTimeout(backend.complete(sessionId), COMPLETE_TIMEOUT_MS);
      if (result?.success) {
        return result.passed ? { outcome: 'passed' } : { outcome: 'failed', message: result.error };
      }
      if (result?.error !== PENDING_MESSAGE) {
        return { outcome: 'failed', message: result?.error };
      }
    } catch {
      // Network blip or timeout: retry below.
    }
    await sleep(1500);
  }
  return { outcome: 'failed', message: 'No pudimos confirmar tu verificación. Intenta de nuevo.' };
};

type Presenter = (purpose: FaceCheckPurpose, backend?: FaceCheckBackend) => Promise<boolean>;
let presenter: Presenter | null = null;
/**
 * The native liveness screen is up. On Android it is its own Activity, so
 * the app briefly reads as backgrounded: the resume lock must not fire for
 * it. Only the capture itself, not the whole Confío Face sheet, counts.
 */
let nativeCaptures = 0;
let lastCaptureEndedAt = 0;
// The capture's promise settles a moment before its screen is gone and the
// app reads as active again, so the flag outlives it briefly.
const CAPTURE_SETTLE_MS = 3000;
export const isFaceCaptureRunning = () =>
  nativeCaptures > 0 || Date.now() - lastCaptureEndedAt < CAPTURE_SETTLE_MS;

let activePresentations = 0;
export const isFaceCheckActive = () => activePresentations > 0;

/** Called once by FaceCheckProvider. */
export const registerFaceCheckPresenter = (fn: Presenter | null) => {
  presenter = fn;
};

/** Show Confío Face and resolve true only when the server passed the check. */
export const ensureFaceCheck = async (
  purpose: FaceCheckPurpose,
  backend?: FaceCheckBackend,
): Promise<boolean> => {
  if (!presenter) return false;
  activePresentations += 1;
  try {
    return await presenter(purpose, backend);
  } finally {
    activePresentations -= 1;
  }
};

/**
 * Run `action`; if the server answers that a face step-up is required, show
 * Confío Face and run it once more. `needsFace` reads the action's result.
 */
export const withFaceStepUp = async <T>(
  purpose: FaceCheckPurpose,
  action: () => Promise<T>,
  needsFace: (result: T) => boolean,
): Promise<T> => {
  const first = await action();
  if (!needsFace(first)) return first;
  const passed = await ensureFaceCheck(purpose);
  if (!passed) throw new FaceCheckError('cancelled', FACE_STEP_UP_MESSAGE);
  return action();
};
