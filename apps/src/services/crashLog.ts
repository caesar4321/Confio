import { getCrashlytics, log, recordError } from '@react-native-firebase/crashlytics';

/**
 * Safe wrapper around Crashlytics breadcrumbs. Crashlytics may not be
 * initialized in dev or if Firebase init fails — callers should never have to
 * worry about that.
 */
export function logBreadcrumb(message: string): void {
  try {
    log(getCrashlytics(), message);
  } catch {
    // Swallow — breadcrumbs are best-effort.
  }
}

export function recordCrashError(error: unknown): void {
  try {
    if (error instanceof Error) {
      recordError(getCrashlytics(), error);
    } else {
      recordError(getCrashlytics(), new Error(String(error)));
    }
  } catch {
    // Swallow.
  }
}

/**
 * Returns a compact `key=type` description of an arbitrary value, useful for
 * identifying which arg of a native bridge call is the wrong type. We never
 * include the value itself (could leak PII into Crashlytics).
 */
export function describeTypes(obj: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    parts.push(`${key}=${value === null ? 'null' : typeof value}`);
  }
  return parts.join(' ');
}
