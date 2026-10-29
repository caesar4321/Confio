import { parseReviewLink } from '../reviewLink';

jest.mock('react-native-keychain', () => ({}));
jest.mock('react-native', () => ({ Alert: { alert: jest.fn() } }));
jest.mock('@apollo/client', () => ({ gql: (s: TemplateStringsArray) => s.join('') }));

describe('parseReviewLink', () => {
  // protects=only confio://review (or /review) with a country and token is a review link; fails_when=other links switch the account's country; no_claim=server token check
  it('reads the custom-scheme and web forms', () => {
    expect(parseReviewLink(new URL('confio://review?country=ar&k=abc'))).toEqual({ country: 'AR', token: 'abc' });
    expect(parseReviewLink(new URL('https://confio.lat/review?country=US&k=x'))).toEqual({ country: 'US', token: 'x' });
  });

  it('ignores anything else or an incomplete link', () => {
    expect(parseReviewLink(new URL('confio://pay/123'))).toBeNull();
    expect(parseReviewLink(new URL('confio://review?country=AR'))).toBeNull();
    expect(parseReviewLink(new URL('https://confio.lat/invite/ana'))).toBeNull();
  });
});
