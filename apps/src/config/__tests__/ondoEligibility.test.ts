import { isOndoPhoneCountryEligible } from '../ondoEligibility';

describe('Ondo client eligibility mirror', () => {
  it('fails closed without a verified phone country', () => {
    expect(isOndoPhoneCountryEligible(undefined)).toBe(false);
    expect(isOndoPhoneCountryEligible('')).toBe(false);
  });

  it('hides prohibited and qualified-only countries', () => {
    expect(isOndoPhoneCountryEligible('US')).toBe(false);
    expect(isOndoPhoneCountryEligible('br')).toBe(false);
    expect(isOndoPhoneCountryEligible('GB')).toBe(false);
  });

  it('allows an issuer-eligible country', () => {
    expect(isOndoPhoneCountryEligible('VE')).toBe(true);
    expect(isOndoPhoneCountryEligible('CO')).toBe(true);
  });
});
