/**
 * FCM data payloads are strings, always.
 *
 * notifications/fcm_service.py builds the push payload with `str(value)` over
 * every entry in the notification's data blob, because FCM only accepts string
 * values. That turns a server-sent `False` into the string "False" — which is
 * truthy in JS, i.e. the exact opposite of what the server said.
 *
 * Two delivery paths used to unpack that payload with two different rules:
 * pushNotificationService parsed the booleans back, messagingService copied
 * them raw. So the same notification meant different things depending on
 * whether it arrived in the foreground or opened the app from the tray, and
 * flags like is_external_address and is_invited_friend silently inverted on
 * one of them. Both paths share this module now so they cannot drift again.
 */

/** Booleans the server sends as strings; truthy-testing these inverts them. */
const BOOLEAN_STRINGS: Record<string, boolean> = {
  true: true,
  false: false,
};

/**
 * Convert one FCM `data_*` value back to the type the server meant.
 * Anything that isn't a recognisable boolean is passed through untouched.
 */
export function parseFcmValue(value: any): any {
  if (typeof value !== 'string') return value;
  const parsed = BOOLEAN_STRINGS[value.trim().toLowerCase()];
  return parsed === undefined ? value : parsed;
}

/**
 * Pull the `data_`-prefixed fields out of an FCM payload, stripping the prefix
 * and restoring boolean types.
 */
export function extractFcmTransactionData(data: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  Object.keys(data || {}).forEach(key => {
    if (!key.startsWith('data_')) return;
    out[key.substring(5)] = parseFcmValue(data[key]);
  });
  return out;
}
