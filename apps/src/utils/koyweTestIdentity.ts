type TestIdentityAvailability = {
  countryCode?: string | null;
  hasTestIdentity?: boolean | null;
};

// Compatibility with the existing overrides in ramps/schema.py. This only
// controls the Koywe screen prompt; order creation still enforces identity
// on the server. Never use this for general KYC or another provider.
const TEST_USERS = new Set(['julianm', 'julianmoonluna']);
const TEST_COUNTRIES = new Set(['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE']);

export function hasKoyweTestIdentity(
  username: string | null | undefined,
  countryCode: string | null | undefined,
  availability?: TestIdentityAvailability | null,
): boolean {
  const country = (countryCode || '').trim().toUpperCase();
  // Once supported, a server decision takes precedence, including denial.
  if (typeof availability?.hasTestIdentity === 'boolean') {
    return availability.countryCode === country && availability.hasTestIdentity;
  }
  // Older servers already substitute these identities at order creation but
  // cannot expose the new availability field. Keep those accounts usable.
  return TEST_USERS.has((username || '').trim().toLowerCase())
    && TEST_COUNTRIES.has(country);
}
