import { parseInstitutionLink } from '../institutionLinks';

describe('institution QR links', () => {
  it('opens public enrollment without an identity claim', () => {
    expect(parseInstitutionLink('https://confio.lat/memberships?provider=cip')).toEqual({ provider: 'cip' });
  });
  it('preserves a personal token for server verification', () => {
    expect(parseInstitutionLink('confio://memberships?provider=cip&token=one.use-token')).toEqual({ provider: 'cip', token: 'one.use-token' });
  });
  it.each([
    'https://confio.lat.evil.test/memberships?provider=cip',
    'https://evil.test/memberships?provider=cip',
    'confio://memberships?provider=cip&provider=other',
    'confio://memberships?provider=cip&token=',
    'confio://memberships?provider=cip&token=%ZZ',
    'confio://memberships?provider=cip&dni=12345678',
    'confio://pay/invoice',
  ])('rejects unsupported or ambiguous URL %s', value => {
    expect(parseInstitutionLink(value)).toBeNull();
  });
});
