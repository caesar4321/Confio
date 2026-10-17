import { hasRampIdentity } from '../rampIdentity';

describe('hasRampIdentity', () => {
  it('reads phoneCountryVerified when the server sends it', () => {
    // Verified only by an additional passport: verified, but not for Koywe.
    expect(hasRampIdentity({ phoneCountryVerified: false }, 'verified')).toBe(false);
    expect(hasRampIdentity({ phoneCountryVerified: true }, undefined)).toBe(true);
  });

  it('otherwise trusts only the primary document attempt', () => {
    expect(hasRampIdentity(undefined, 'VERIFIED')).toBe(true);
    expect(hasRampIdentity({ phoneCountryVerified: null }, 'pending')).toBe(false);
    expect(hasRampIdentity(null, null)).toBe(false);
  });
});
