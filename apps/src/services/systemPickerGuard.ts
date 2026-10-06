/**
 * The OS photo picker is a separate app: while it is open Confío is in the
 * background, and the resume lock (AuthContext: away > 10 s locks, and the
 * unlock lands on Home) used to fire on the way back. Picking a photo slowly
 * then dumped people on Home and lost what they were doing.
 *
 * Like the face-capture exemption, an open picker is not "leaving the app",
 * but only for a bounded time: a phone left sitting in the picker still
 * locks on return.
 */
let openPickers = 0;
let openedAt = 0;
let lastClosedAt = 0;

/** Returning within this after the picker closes still counts as the picker. */
const SETTLE_MS = 3000;
/** Never exempt more than this: a longer absence locks as usual. */
export const SYSTEM_PICKER_MAX_MS = 3 * 60 * 1000;

export async function withSystemPicker<T>(run: () => Promise<T>): Promise<T> {
  openPickers += 1;
  openedAt = Date.now();
  try {
    return await run();
  } finally {
    openPickers = Math.max(0, openPickers - 1);
    lastClosedAt = Date.now();
  }
}

export function isSystemPickerOpen(now: number = Date.now()): boolean {
  if (now - openedAt > SYSTEM_PICKER_MAX_MS) return false;
  return openPickers > 0 || now - lastClosedAt < SETTLE_MS;
}

/** Test hook. */
export function resetSystemPickerForTests() {
  openPickers = 0;
  openedAt = 0;
  lastClosedAt = 0;
}
