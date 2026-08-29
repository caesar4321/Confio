import { shouldSkipStoredJwt } from '../authPolicy';

describe('Apollo authentication policy', () => {
  it('never attaches a stored JWT while establishing a fresh login session', () => {
    expect(shouldSkipStoredJwt('Web3AuthLogin')).toBe(true);
  });

  it('keeps token refresh independent of an expired stored access token', () => {
    expect(shouldSkipStoredJwt('RefreshToken')).toBe(true);
  });

  it('honours an explicit anonymous-operation override', () => {
    expect(shouldSkipStoredJwt('LegalDocument', true)).toBe(true);
  });

  it('requires stored authentication for ordinary operations', () => {
    expect(shouldSkipStoredJwt('GetUserProfile')).toBe(false);
    expect(shouldSkipStoredJwt(undefined)).toBe(false);
  });
});
