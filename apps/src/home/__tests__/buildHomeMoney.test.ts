import { buildHomeMoney, type HomeMoneyInput } from '../buildHomeMoney';

const calls: string[] = [];
const call = (key: string) => () => { calls.push(key); };
const input = (over: Partial<HomeMoneyInput> = {}): HomeMoneyInput => ({
  ready: true,
  masked: false,
  canToggle: true,
  totalText: 'US$254,30',
  currencyCode: 'USD',
  currencyHint: 'Mostrar en bolivianos',
  accounts: [
    { id: 'personal_0', name: 'Ana Pérez', kind: 'Personal', avatar: 'A', selected: true },
    { id: 'business_1_0', name: 'Panadería', kind: 'Negocio', avatar: 'P', selected: false },
  ],
  month: { kind: 'loading' },
  balancesKnown: true,
  dollar: { plus: true, usd: 210.109 },
  legacyDollarUsd: null,
  investments: { visible: true, totalKnown: true, totalUsd: 40.2 },
  confioTotal: 4,
  smart: { subscriber: false, totalUsd: null, canSubscribe: true },
  actionIds: ['send', 'receive'],
  primaryAction: 'send',
  noticeKey: null,
  pendingPayrollCount: 0,
  ...over,
});
const tile = (money: ReturnType<typeof buildHomeMoney>, key: string) => money.tiles.find((t) => t.key === key);
// The country's separators come from the number locale: compare digits only.
const digits = (text: string | null | undefined) => (text ?? '').replace(/[^\d]/g, '');

beforeEach(() => { calls.length = 0; });

it('floors amounts (never rounds a balance up) and writes them as US$', () => {
  const money = buildHomeMoney(input(), call);
  // The total arrives written (in dollars or the local currency) from Inicio.
  expect(money.total).toBe('US$254,30');
  expect(digits(tile(money, 'dollar')?.amount)).toBe('21010');
  expect(tile(money, 'dollar')?.amount?.startsWith('US$')).toBe(true);
  // A token count: no currency sign.
  expect(digits(tile(money, 'confio')?.amount)).toBe('400');
  expect(tile(money, 'confio')?.amount).not.toContain('$');
});

it('orders the wallets: dollar, legacy, investments, $CONFIO, and Cuenta inteligente last', () => {
  const money = buildHomeMoney(input({ legacyDollarUsd: 3 }), call);
  expect(money.tiles.map((t) => t.key)).toEqual(['dollar', 'legacy', 'invest', 'confio', 'smart']);
  expect(money.tiles.map((t) => t.label)).toEqual(
    ['Confío Dollar+', 'Antiguo Confío Dollar', 'Inversiones', '$CONFIO', 'Cuenta inteligente']);
});

it('eligibility alone names the dollar; absent rows are absent', () => {
  const money = buildHomeMoney(input({
    dollar: { plus: false, usd: 5 }, investments: { visible: false, totalKnown: false, totalUsd: 0 }, smart: null,
  }), call);
  expect(money.tiles.map((t) => t.label)).toEqual(['Confío Dollar', '$CONFIO']);
});

it('a hidden balance masks every amount, in text and for a screen reader', () => {
  const money = buildHomeMoney(input({
    masked: true, legacyDollarUsd: 3, smart: { subscriber: true, totalUsd: '99.50', canSubscribe: false },
  }), call);
  expect(money.masked).toBe(true);
  expect(money.total).toBe('••••••');
  for (const t of money.tiles) {
    expect(t.amount).toBe('••••');
    expect(t.accessibilityLabel).toContain('saldo oculto');
    expect(t.accessibilityLabel).not.toMatch(/\d/);
  }
});

it('an unknown balance is a dash, never a zero', () => {
  const money = buildHomeMoney(input({
    investments: { visible: true, totalKnown: false, totalUsd: 0 }, confioTotal: null,
    smart: { subscriber: true, totalUsd: null, canSubscribe: false },
  }), call);
  for (const key of ['invest', 'confio', 'smart']) {
    expect(tile(money, key)?.amount).toBe('—');
    expect(tile(money, key)?.accessibilityLabel).toContain('saldo no disponible');
  }
});

it('Cuenta inteligente is an offer until the person has it: no amount, "Activar" or "Ver"', () => {
  const offer = tile(buildHomeMoney(input(), call), 'smart');
  expect(offer?.amount).toBeNull();
  expect(offer?.offerLabel).toBe('Activar');
  // A beneficiary who cannot subscribe still has something to see.
  expect(tile(buildHomeMoney(input({ smart: { subscriber: false, totalUsd: null, canSubscribe: false } }), call), 'smart')?.offerLabel)
    .toBe('Ver');
  const owned = tile(buildHomeMoney(input({ smart: { subscriber: true, totalUsd: '99.509', canSubscribe: false } }), call), 'smart');
  expect(digits(owned?.amount)).toBe('9950');
  expect(owned?.offerLabel).toBeUndefined();
});

it('draws no wallets until both balance reads are in', () => {
  const money = buildHomeMoney(input({ ready: false, balancesKnown: false }), call);
  expect(money.tiles).toEqual([]);
  expect(money.ready).toBe(false);
});

it('the two verbs keep their order; only the emphasis moves, and a lone verb is filled', () => {
  const both = buildHomeMoney(input({ primaryAction: 'receive' }), call);
  expect(both.actions.map((a) => [a.id, a.label, a.filled])).toEqual([['send', 'Enviar', false], ['receive', 'Recibir', true]]);
  const one = buildHomeMoney(input({ actionIds: ['send'], primaryAction: 'receive' }), call);
  expect(one.actions.map((a) => [a.id, a.filled])).toEqual([['send', true]]);
  expect(buildHomeMoney(input({ actionIds: [] }), call).actions).toEqual([]);
});

it('Cuenta inteligente not known yet: the same tile with a dash, never the offer turning into a balance', () => {
  const pending = tile(buildHomeMoney(input({ smart: { known: false, subscriber: false, totalUsd: null, canSubscribe: false } }), call), 'smart');
  expect(pending?.amount).toBe('—');
  expect(pending?.offerLabel).toBeUndefined();
});

it('the menu row for Cuenta inteligente does not wait for the balances', () => {
  const money = buildHomeMoney(input({ balancesKnown: false }), call);
  expect(money.tiles).toEqual([]);
  money.openSmart?.();
  expect(calls).toContain('smart');
  expect(buildHomeMoney(input({ smart: null }), call).openSmart).toBeNull();
});

it('every tap goes through the named handler', () => {
  const money = buildHomeMoney(input({ noticeKey: 'pendingIncoming' }), call);
  money.toggleBalance();
  money.toggleCurrency();
  money.refresh();
  money.openMonth();
  money.tiles.forEach((t) => t.onPress());
  money.actions.forEach((a) => a.onPress());
  money.notice?.onPress();
  money.switchAccount('business_1_0');
  money.createBusiness();
  expect(calls).toEqual(['toggleBalance', 'toggleCurrency', 'refresh', 'openMonth', 'dollar', 'invest', 'confio', 'smart',
    'send', 'receive', 'pendingIncoming', 'switchAccount:business_1_0', 'createBusiness']);
});

it('carries the accounts for the menu\'s switcher and the currency the total is written in', () => {
  const money = buildHomeMoney(input({ currencyCode: 'BOB', currencyHint: 'Mostrar en dólares' }), call);
  expect(money.accounts.map((a) => [a.name, a.kind, a.selected])).toEqual(
    [['Ana Pérez', 'Personal', true], ['Panadería', 'Negocio', false]]);
  expect(money.currencyCode).toBe('BOB');
  expect(money.currencyHint).toBe('Mostrar en dólares');
});

it('one notice at most, worded for what is waiting', () => {
  expect(buildHomeMoney(input(), call).notice).toBeNull();
  expect(buildHomeMoney(input({ noticeKey: 'pendingIncoming' }), call).notice)
    .toMatchObject({ key: 'pendingIncoming', text: 'Tienes dinero por recibir' });
  expect(buildHomeMoney(input({ noticeKey: 'payroll', pendingPayrollCount: 1 }), call).notice?.text)
    .toBe('Tienes 1 pago de nómina para firmar');
  expect(buildHomeMoney(input({ noticeKey: 'payroll', pendingPayrollCount: 3 }), call).notice?.text)
    .toBe('Tienes 3 pagos de nómina para firmar');
  expect(buildHomeMoney(input({ noticeKey: 'dues' }), call).notice?.text).toBe('Tienes una cuota por pagar');
});
