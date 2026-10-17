/**
 * "Share to Comunidad" requests from any screen, without hooks.
 *
 * A screen calls `requestActivityShare` the moment it knows a movement
 * succeeded; the single CommunityShareProvider (mounted once above the
 * authenticated navigator) shows the share sheet above whatever screen is
 * up, so leaving the success screen never closes it.
 *
 * Each (group, reference) opens at most once per app session, and only one
 * sheet shows at a time: a request that arrives while one is open is
 * dropped (and may be asked again later).
 */

export type ActivityShareGroup = 'stock' | 'send' | 'ramp' | 'pay';

export type ActivityShareRequest = {
  group: ActivityShareGroup;
  /** stock → trade tx hash; send → SendTransaction internalId; ramp → Koywe orderId or Infinia journey internalId. */
  reference: string | null | undefined;
};

/** Returns true when the request was taken (the sheet is now handling it). */
type Listener = (request: { group: ActivityShareGroup; reference: string }) => boolean;

let listener: Listener | null = null;
const opened = new Set<string>();

const keyFor = (group: string, reference: string) => `${group}:${reference}`;

export function requestActivityShare({ group, reference }: ActivityShareRequest): boolean {
  const ref = (reference || '').trim();
  if (!ref || !listener) return false;
  const key = keyFor(group, ref);
  if (opened.has(key)) return false;
  let taken = false;
  try {
    taken = listener({ group, reference: ref });
  } catch {
    taken = false;
  }
  if (taken) opened.add(key);
  return taken;
}

/** The provider registers itself here; returns the unregister function. */
export function setActivityShareListener(next: Listener): () => void {
  listener = next;
  return () => {
    if (listener === next) listener = null;
  };
}

/** Tests only. */
export function resetActivityShareForTests() {
  listener = null;
  opened.clear();
}
