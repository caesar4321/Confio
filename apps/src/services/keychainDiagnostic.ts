// How long this phone's keystore took to hand over the stored session, for
// this process. Kept apart from sessionStore so the request-header helper can
// read it without loading the keychain library.
let firstReadMs: number | null = null;
let maxReadMs = 0;
let readCount = 0;
let storageKind = '';
// Whether the in-memory session is in use (its keychain observer installed).
let cacheActive = false;

export function setSessionCacheActive(active: boolean) {
  cacheActive = active;
}

export function recordKeychainRead(elapsedMs: number, storage?: unknown) {
  if (firstReadMs === null) firstReadMs = elapsedMs;
  if (elapsedMs > maxReadMs) maxReadMs = elapsedMs;
  readCount += 1;
  if (typeof storage === 'string') storageKind = storage;
}

/** `first=<ms>;max=<ms>;n=<reads>;c=<0|1>;st=<storage>`, or null before the first keychain read. Timings only. */
export function getKeychainDiagnostic(): string | null {
  if (firstReadMs === null) return null;
  const storage = storageKind.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40);
  return `first=${firstReadMs};max=${maxReadMs};n=${readCount};c=${cacheActive ? 1 : 0}${storage ? `;st=${storage}` : ''}`;
}

/** Tests only. */
export function resetKeychainDiagnosticForTests() {
  firstReadMs = null;
  maxReadMs = 0;
  readCount = 0;
  storageKind = '';
  cacheActive = false;
}
