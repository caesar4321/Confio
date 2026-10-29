import { hasRampIdentity, needsCountryDocument } from '../rampIdentity';

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

describe('country-aware ramp identity', () => {
  // protects=Recargar opens only with a document issued by the selected country; fails_when=any verified document opens every country; no_claim=Koywe's own acceptance
  it('reads verifiedDocumentCountries for the selected country first', () => {
    const identity = { phoneCountryVerified: true, verifiedDocumentCountries: ['VE'] };
    expect(hasRampIdentity(identity, 'verified', 'CO')).toBe(false);
    expect(hasRampIdentity(identity, 'verified', 've')).toBe(true);
  });

  it('falls back to phoneCountryVerified on servers without the list', () => {
    expect(hasRampIdentity({ phoneCountryVerified: true }, undefined, 'CO')).toBe(true);
  });

  it('asks for this country\'s document only when another country\'s is verified', () => {
    expect(needsCountryDocument({ verifiedDocumentCountries: ['VE'] }, 'CO')).toBe(true);
    expect(needsCountryDocument({ verifiedDocumentCountries: [] }, 'CO')).toBe(false);
    expect(needsCountryDocument({ verifiedDocumentCountries: ['CO'] }, 'CO')).toBe(false);
  });
});

