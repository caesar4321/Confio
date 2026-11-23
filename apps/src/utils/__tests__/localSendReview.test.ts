import { isUnsupportedMode, reviewStillMatches } from '../localSendReview';

const terms = { amount: '92.80', destinationId: 'd-1', exactLocal: '500.00' };

describe('reviewStillMatches', () => {
  it('signs only what was reviewed', () => {
    expect(reviewStillMatches(terms, { ...terms })).toBe(true);
    expect(reviewStillMatches(null, terms)).toBe(false);
    expect(reviewStillMatches(terms, { ...terms, amount: '92.81' })).toBe(false);
    expect(reviewStillMatches(terms, { ...terms, destinationId: 'd-2' })).toBe(false);
    // A new exact amount, or leaving local-currency mode, is a new review.
    expect(reviewStillMatches(terms, { ...terms, exactLocal: '501.00' })).toBe(false);
    expect(reviewStillMatches(terms, { ...terms, exactLocal: '' })).toBe(false);
  });
});

describe('isUnsupportedMode', () => {
  it('tells an older server from a passing error', () => {
    expect(isUnsupportedMode(new Error('Cannot query field "localExactSend" on type "Query".'))).toBe(true);
    expect(isUnsupportedMode(new Error('Unknown argument "exactLocal" on field "Query.localPayoutQuote".'))).toBe(true);
    expect(isUnsupportedMode(new Error('Network request failed'))).toBe(false);
    expect(isUnsupportedMode(undefined)).toBe(false);
  });
});
