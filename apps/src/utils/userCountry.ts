/**
 * Where the signed-in user lives: the server's `me.country` (residence,
 * security.geo.country_of). `phoneCountry` is only the phone number's
 * country, and phone-less accounts have none; it is the fallback for a
 * profile cached before `country` existed.
 */
export const userCountryIso = (
  profile?: { country?: string | null; phoneCountry?: string | null } | null,
): string => String(profile?.country || profile?.phoneCountry || '').trim().toUpperCase();
