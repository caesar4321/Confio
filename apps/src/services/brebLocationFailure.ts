/** A failure of the Bre-B location check itself (permission, device, server),
 * not of the operation that needed it. Kept apart from brebLocation.ts so a
 * screen can recognize one without loading the location service. */
export const isBrebLocationFailure = (error: unknown): boolean => Boolean((error as any)?.brebLocation);
