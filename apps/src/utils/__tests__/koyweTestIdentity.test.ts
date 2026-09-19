import { hasKoyweTestIdentity } from '../koyweTestIdentity';

describe('Koywe test identity compatibility', () => {
  it.each(['julianm', 'julianmoonluna'])('allows %s on the current backend in every configured test country', username => {
    for (const country of ['AR', 'BO', 'BR', 'CL', 'CO', 'MX', 'PE']) {
      expect(hasKoyweTestIdentity(username, country)).toBe(true);
    }
  });

  it('matches backend normalization', () => {
    expect(hasKoyweTestIdentity(' JULIANM ', ' bo ')).toBe(true);
  });

  it.each([undefined, null, '', 'ordinary-user', 'julianmoon', '@julianm'])('does not exempt other or unloaded users: %s', username => {
    expect(hasKoyweTestIdentity(username, 'BO')).toBe(false);
  });

  it.each([undefined, null, '', 'US', 'VE'])('does not exempt unsupported or unresolved countries: %s', country => {
    expect(hasKoyweTestIdentity('julianm', country)).toBe(false);
  });

  it('honors explicit server denial over the compatibility list', () => {
    expect(hasKoyweTestIdentity('julianm', 'BO', { countryCode: 'BO', hasTestIdentity: false })).toBe(false);
  });

  it('honors a server-granted identity', () => {
    expect(hasKoyweTestIdentity('future-test-user', 'BO', { countryCode: 'BO', hasTestIdentity: true })).toBe(true);
  });

  it('does not reuse a server decision from another country', () => {
    expect(hasKoyweTestIdentity('julianm', 'BO', { countryCode: 'AR', hasTestIdentity: true })).toBe(false);
  });
});
