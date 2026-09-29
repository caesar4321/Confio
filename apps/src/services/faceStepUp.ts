/**
 * Confío Face — prove it's you before money moves.
 *
 * The server asks for a face step-up (next_step 'face_check', or the exact
 * FACE_STEP_UP_MESSAGE) before a deposit order, a withdrawal, or a send to an
 * external address. We open an AWS Face Liveness capture with credentials
 * the server scopes to that one session, then the server grades it against
 * the KYC selfie and only tells us pass/fail.
 *
 * Service code (sends, journeys) runs outside React, so the modal host
 * (FaceCheckProvider) registers a presenter here and callers use
 * `ensureFaceCheck` / `withFaceStepUp`.
 */
import { gql } from '@apollo/client';
import { NativeModules } from 'react-native';

export type FaceCheckPurpose = 'on_ramp' | 'withdrawal' | 'emergency_exit';
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
    }
  }
`;

/** Whether the server enforces Confío Face; null when it cannot be read. */
export const fetchFaceStepUpStatus = async (): Promise<{ enabled: boolean } | null> => {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({ query: STATUS, fetchPolicy: 'network-only' });
    return data?.faceStepUpStatus ? { enabled: !!data.faceStepUpStatus.enabled } : null;
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

/** Server session → native capture → server grade. Never throws. */
export const runFaceCapture = async (
  purpose: FaceCheckPurpose,
  onGrading?: () => void,
): Promise<{ outcome: FaceCaptureOutcome; message?: string }> => {
  const native = NativeModules.ConfioFaceLiveness;
  if (!native?.start) {
    return { outcome: 'unavailable', message: 'Actualiza Confío para confirmar tu identidad.' };
  }
  const { apolloClient } = await import('../apollo/client');
  let start;
  try {
    const { data } = await withTimeout(
      apolloClient.mutate({ mutation: START, variables: { purpose } }), START_TIMEOUT_MS);
    start = data?.startFaceCheck;
  } catch {
    return { outcome: 'unavailable', message: 'Revisa tu conexión e intenta de nuevo.' };
  }
  if (!start?.success) {
    return { outcome: 'unavailable', message: start?.error || 'No pudimos iniciar la verificación.' };
  }
  try {
    await native.start(start.sessionId, start.region, {
      accessKeyId: start.accessKeyId,
      secretAccessKey: start.secretAccessKey,
      sessionToken: start.sessionToken,
      expirationEpochSeconds: Math.floor(Date.parse(start.expiration) / 1000),
    });
  } catch (error: any) {
    if (error?.code === 'UserCancelledException') return { outcome: 'cancelled' };
    if (CAMERA_DENIED_CODES.has(error?.code)) return { outcome: 'unavailable', message: CAMERA_DENIED_MESSAGE };
    // A capture error still lets the server record the session as failed.
  }
  onGrading?.();
  // AWS may still be processing the video: the server answers PENDING_MESSAGE
  // and the same call is safe to repeat.
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const { data } = await withTimeout(apolloClient.mutate({
        mutation: COMPLETE,
        variables: { sessionId: start.sessionId },
      }), COMPLETE_TIMEOUT_MS);
      const result = data?.completeFaceCheck;
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

type Presenter = (purpose: FaceCheckPurpose) => Promise<boolean>;
let presenter: Presenter | null = null;

/** Called once by FaceCheckProvider. */
export const registerFaceCheckPresenter = (fn: Presenter | null) => {
  presenter = fn;
};

/** Show Confío Face and resolve true only when the server passed the check. */
export const ensureFaceCheck = async (purpose: FaceCheckPurpose): Promise<boolean> => {
  if (!presenter) return false;
  return presenter(purpose);
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
