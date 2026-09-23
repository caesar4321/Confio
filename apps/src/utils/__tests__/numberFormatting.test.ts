jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: null }) }));

import { formatNumber } from '../numberFormatting';

describe('formatNumber fraction digits', () => {
  it('prints whole counts when only the maximum is capped', () => {
    // Regression: the default minimum of 2 made Intl throw and the fallback
    // showed "312.00 participantes".
    expect(formatNumber(312, 'AR', { maximumFractionDigits: 0 })).toBe('312');
    expect(formatNumber(1234, 'AR', { maximumFractionDigits: 0 })).toBe('1.234');
  });

  it('keeps two decimals by default', () => {
    expect(formatNumber(4.5, 'AR')).toBe('4,50');
  });

  it('widens the maximum when only a larger minimum is given', () => {
    expect(formatNumber(0.2004, 'AR', { minimumFractionDigits: 4 })).toBe('0,2004');
  });
});
