import {
  ensureFaceCheck, fetchFaceStepUpStatus, FaceCheckMovement, FaceCheckPurpose, isFaceCheckActive, movementBackend,
} from './faceStepUp';

/** No device-auth fallback, cached approval, or inference from a failed query.
 * A server-confirmed non-KYC user needs no additional authentication.
 * Unlock approvals have their own purpose and cannot authorize money out.
 */
let active = 0;
export const isFaceAuthenticating = () => active > 0 || isFaceCheckActive();

/** `movement`, when known, lets a small movement inside Confío get the light check. */
export async function authenticateWithFace(
  purpose: FaceCheckPurpose = 'withdrawal',
  movement?: FaceCheckMovement,
): Promise<boolean> {
  active += 1;
  try {
    const status = await fetchFaceStepUpStatus();
    if (!status?.enabled || status.required === null) return false;
    if (!status.required) return true;
    return await ensureFaceCheck(purpose, movement ? movementBackend(movement) : undefined);
  } catch {
    return false;
  } finally {
    active -= 1;
  }
}
