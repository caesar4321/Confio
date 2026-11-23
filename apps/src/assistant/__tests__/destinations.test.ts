const mockNavigate = jest.fn();
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...args: unknown[]) => mockNavigate(...args) },
}));
jest.mock('../../utils/balanceVisibility', () => ({ isBalanceHidden: () => Promise.resolve(false) }));
// A build constant: each test picks the navigation it is about.
let mockConversationHome = false;
jest.mock('../../config/features', () => {
  const mock = {};
  Object.defineProperties(mock, Object.getOwnPropertyDescriptors(jest.requireActual('../../config/features')));
  Object.defineProperty(mock, 'CONVERSATION_HOME_ENABLED', { get: () => mockConversationHome });
  return mock;
});

import {
  DESTINATION_CARDS, DESTINATION_LABELS, DESTINATION_TARGETS, PAID_OFFER_KEYS, cardFor, openDestination, resolveNavigate,
} from '../destinations';
import { HIDDEN_ROUTES } from '../suggestions';

beforeEach(() => {
  mockNavigate.mockClear();
  mockConversationHome = false;
});

describe('"Abre QR para pagar"', () => {
  it('five tabs: the Pagar tab, or Cobrar for a business', () => {
    expect(openDestination('pay_qr')).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Scan', params: undefined } });
    expect(openDestination('pay_qr', { isBusiness: true })).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Charge', params: undefined } });
  });

  it('conversation home: there is no Pagar tab, so the scanner opens as a stack screen', () => {
    mockConversationHome = true;
    expect(openDestination('pay_qr')).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'Scan', params: { mode: 'pagar' } });
    // A business still has Cobrar as a route.
    expect(openDestination('pay_qr', { isBusiness: true })).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Charge', params: undefined } });
  });
});

describe('everything has a door from the chat', () => {
  it('each new key opens its own screen', () => {
    const screens: Record<string, [string, object?]> = {
      charge: ['Charge'], invite: ['Invite'], commissions: ['FeeReferralCommissions'], agenda: ['Agenda'],
      ramp_history: ['RampHistory'], stocks_activity: ['StocksActivity'], league: ['League'],
      community_post: ['CommunityCompose'], notification_settings: ['NotificationSettings'],
      edit_profile: ['EditProfile'], username: ['UpdateUsername'], share_username: ['ConfioAddress'],
      memberships: ['Memberships'], create_business: ['CreateBusiness'], payroll: ['PayrollHome'],
      employees: ['Employees'], terms: ['LegalDocument', { docType: 'terms' }],
    };
    for (const [key, [screen, params]] of Object.entries(screens)) {
      expect(openDestination(key)).toBe(true);
      expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen, params });
    }
    // A business edits the business, not a person's profile.
    expect(openDestination('edit_profile', { isBusiness: true })).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'EditBusiness', params: undefined });
  });

  it('a wallet opens as its tile in the menu opens it; with no home mounted, Inicio has it', () => {
    const { registerHomeMoneyReader } = require('../../home/homeMoneyStore');
    const dollar = jest.fn();
    const confio = jest.fn();
    mockConversationHome = true;
    const undo = registerHomeMoneyReader(() => ({ tiles: [{ key: 'dollar', onPress: dollar }, { key: 'confio', onPress: confio }] }));
    expect(openDestination('wallet_dollar')).toBe(true);
    expect(openDestination('wallet_confio')).toBe(true);
    expect(dollar).toHaveBeenCalledTimes(1);
    expect(confio).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
    undo();
    expect(openDestination('wallet_dollar')).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home', params: undefined } });
  });

  it('every key has a name and a card that says what the screen is for', () => {
    for (const key of Object.keys(DESTINATION_TARGETS)) {
      expect(DESTINATION_LABELS[key]).toBeTruthy();
      expect(DESTINATION_CARDS[key]?.icon).toBeTruthy();
      expect(DESTINATION_CARDS[key]?.hint.length).toBeGreaterThan(8);
      // One line under the name on a small phone.
      expect(DESTINATION_CARDS[key].hint.length).toBeLessThanOrEqual(30);
    }
    expect(cardFor('nope')).toEqual({ icon: 'arrow-up-right', hint: '' });
    mockConversationHome = true;
    expect(cardFor('home').icon).toBe('credit-card');
  });

  it('no two different screens share an icon', () => {
    // The same screen under two keys may share one; different screens may not.
    const same = [['discover', 'community'], ['ia_plus', 'cuenta_inteligente']];
    const seen = new Map<string, string>();
    for (const [key, card] of Object.entries(DESTINATION_CARDS)) {
      const twin = seen.get(card.icon);
      if (twin) expect(same.some((pair) => pair.includes(key) && pair.includes(twin))).toBe(true);
      else seen.set(card.icon, key);
    }
    // Pagar, Cobrar and Cuenta inteligente wear the app's own marks.
    expect([DESTINATION_CARDS.pay_qr.icon, DESTINATION_CARDS.charge.icon, DESTINATION_CARDS.cuenta_inteligente.icon])
      .toEqual(['qr-pay', 'qr-show', 'smart-account']);
  });
});

describe('the conversation home', () => {
  it('a tab route opens exactly as in the five-tab app: the screen the person was on stays underneath', () => {
    for (const on of [true, false]) {
      mockConversationHome = on;
      expect(openDestination('profile')).toBe(true);
      expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Profile', params: undefined } });
    }
  });

  it('everything that lives in Invertir asks for it by name (there is no segment bar to switch back with)', () => {
    mockConversationHome = true;
    for (const key of ['invest', 'stocks', 'presale']) {
      expect(openDestination(key)).toBe(true);
      const [, target] = mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1];
      expect(target.params.screen).toBe('Invest');
      expect(target.params.params.segment).toBe('invest');
    }
    expect(openDestination('community')).toBe(true);
    expect(mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1][1].params.params.segment).toBe('community');
    // Five tabs: `stocks` opens the tab as it stands, as before.
    mockConversationHome = false;
    expect(openDestination('stocks')).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Invest', params: undefined } });
  });

  it('`home` is "Mi dinero" there: its chip says so, and opens the menu when a home is mounted', () => {
    const { registerHomeMenu } = require('../../home/homeMoneyStore');
    expect(resolveNavigate({ destination: 'home' })?.label).toBe('Ir a Inicio');
    mockConversationHome = true;
    expect(resolveNavigate({ destination: 'home' })?.label).toBe('Ver mi dinero');
    const opener = jest.fn();
    const undo = registerHomeMenu(opener);
    expect(openDestination('home')).toBe(true);
    expect(opener).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
    undo();
    // No conversation home mounted (a Cuenta inteligente context): its own Inicio.
    expect(openDestination('home')).toBe(true);
    expect(mockNavigate).toHaveBeenLastCalledWith('Main', { screen: 'BottomTabs', params: { screen: 'Home', params: undefined } });
  });

  it('the old Descubrir key is labelled as what it opens', () => {
    expect(resolveNavigate({ destination: 'discover' })?.label).toBe('Abrir Comunidad');
  });
});

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
