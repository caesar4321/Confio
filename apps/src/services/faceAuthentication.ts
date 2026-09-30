import { ensureFaceCheck, fetchFaceStepUpStatus, FaceCheckPurpose, isFaceCheckActive } from './faceStepUp';

/** No device-auth fallback, cached approval, or inference from a failed query.
 * A server-confirmed non-KYC user needs no additional authentication.
 * Unlock approvals have their own purpose and cannot authorize money out.
 */
let active = 0;
export const isFaceAuthenticating = () => active > 0 || isFaceCheckActive();

export async function authenticateWithFace(purpose: FaceCheckPurpose = 'withdrawal'): Promise<boolean> {
  active += 1;
  try {
    const status = await fetchFaceStepUpStatus();
    if (!status?.enabled || status.required === null) return false;
    if (!status.required) return true;
    return await ensureFaceCheck(purpose);
  } catch {
    return false;
  } finally {
    active -= 1;
  }
}
