const mockNavigate = jest.fn();
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...args: unknown[]) => mockNavigate(...args) },
}));
jest.mock('../../utils/balanceVisibility', () => ({ isBalanceHidden: () => Promise.resolve(false) }));

import { DESTINATION_TARGETS, PAID_OFFER_KEYS, openDestination, resolveNavigate } from '../destinations';
import { HIDDEN_ROUTES } from '../suggestions';

beforeEach(() => mockNavigate.mockClear());

describe('Cuenta inteligente doors from Confio Assistant', () => {
  it('open the real offer as a chip, never the old waitlist probe', () => {
    for (const key of ['cuenta_inteligente', 'ia_plus']) {
      mockNavigate.mockClear();
      expect(openDestination(key)).toBe(true);
      expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountOffer', params: { door: 'chip' } });
    }
  });

  it('no destination opens the removed PaidOffer screen', () => {
    for (const target of Object.values(DESTINATION_TARGETS)) {
      expect('screen' in target ? target.screen : target.tab).not.toBe('PaidOffer');
    }
    expect(HIDDEN_ROUTES.has('PaidOffer')).toBe(false);
    expect(HIDDEN_ROUTES.has('SmartAccountOffer')).toBe(true);
  });

  it('the chip keeps the current name and stays tap-only', () => {
    expect(resolveNavigate({ destination: 'home', target: 'cuenta_inteligente', label: 'Conoce Confío IA+' }))
      .toEqual({ key: 'cuenta_inteligente', ticker: undefined, label: 'Conoce Cuenta inteligente' });
    expect(PAID_OFFER_KEYS.has('cuenta_inteligente')).toBe(true);
  });
});

describe('Confío IA+ rule proposal chip (decision 34)', () => {
  const { TAP_ONLY_KEYS } = require('../destinations');

  it('is known to this build, tap-only, and keeps its own label', () => {
    expect(resolveNavigate({ destination: 'cuenta_inteligente', target: 'smart_account_rule', label: 'x' }))
      .toEqual({ key: 'smart_account_rule', ticker: undefined, label: 'x' });
    expect(TAP_ONLY_KEYS.has('smart_account_rule')).toBe(true);
    expect(PAID_OFFER_KEYS.has('smart_account_rule')).toBe(false);
  });

  it('an older build falls back to the Cuenta inteligente door', () => {
    expect(resolveNavigate({ destination: 'cuenta_inteligente', target: 'not_known_yet' })?.key)
      .toBe('cuenta_inteligente');
  });

  it('without a message id it opens the rules list', async () => {
    expect(openDestination('smart_account_rule')).toBe(true);
    await Promise.resolve();
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'SmartAccountRules' });
  });
});
