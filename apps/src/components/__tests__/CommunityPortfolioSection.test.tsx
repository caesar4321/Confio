import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Pressable, Switch } from 'react-native';
import { CommunityMemberPortfolio, CommunityPortfolioSection } from '../CommunityPortfolioSection';


// These suites describe the Android build; DEX_TRADING_UI_ENABLED is
// Platform-derived and the Jest preset runs as iOS. Flip per test for the iOS binary.
const mockFeatures = { DEX_TRADING_UI_ENABLED: true };
jest.mock('../../config/features', () => {
  const mocked = { __esModule: true, ...jest.requireActual('../../config/features') };
  // A live getter, read at render time (a spread would copy one value at load).
  Object.defineProperty(mocked, 'DEX_TRADING_UI_ENABLED', {
    enumerable: true,
    get: () => mockFeatures.DEX_TRADING_UI_ENABLED,
  });
  return mocked;
});
afterEach(() => { mockFeatures.DEX_TRADING_UI_ENABLED = true; });

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
const mockNavigate = jest.fn();
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { type: 'personal' } }) }));

const base: CommunityMemberPortfolio = {
  userId: '7',
  isSelf: false,
  hidden: false,
  totalUsd: '11658.03',
  dollarsUsd: '1000.00',
  stocksUsd: '10658.03',
  stocksChange24hUsd: '-12.50',
  presaleConfio: '0.00',
  presaleInvestedUsd: null,
  tradeCount: 3,
  avgHoldSeconds: 7 * 3600 + 53 * 60,
  memberSince: '2026-10',
  openPositions: [
    {
      symbol: 'AAPLon', ticker: 'AAPL', name: 'Apple', units: '2.500000', valueUsd: '500.00',
      investedUsd: '450.00', avgEntryUsd: '180.0000', pnlUsd: '50.00', pnlPct: '11.11', dayChangePct: '0.40',
    },
    {
      symbol: 'TSLAon', ticker: 'TSLA', name: 'Tesla', units: '1', valueUsd: '300.00',
      investedUsd: null, avgEntryUsd: null, pnlUsd: null, pnlPct: null, dayChangePct: null,
    },
  ],
  closedPositions: [],
};

const textOf = (tree: renderer.ReactTestRenderer) =>
  tree.root
    .findAll((node) => typeof node.props.children === 'string' || Array.isArray(node.props.children))
    .map((node) => (Array.isArray(node.props.children) ? node.props.children.filter((c: unknown) => typeof c === 'string').join('') : node.props.children))
    .join('|');

test('renders totals, stats and open positions; hides a zero CONFIO row', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CommunityPortfolioSection portfolio={base} />); });
  const text = textOf(tree);
  expect(text).toContain('3 trades');
  expect(text).toContain('7h 53m de media por posición');
  expect(text).toContain('Se unió en oct 2026');
  expect(text).toContain('$11,658');
  expect(text).toContain('-$12.50 en 24 h');
  expect(text).toContain('$10,658.03');
  expect(text).not.toContain('CONFIO (preventa)');
  expect(text).toContain('Abiertas (2)');
  expect(text).toContain('▲ 11.11%');
  expect(tree.root.findAllByType(Switch)).toHaveLength(0);
  expect(text).not.toContain('Invertido');

  const rows = tree.root.findAllByType(Pressable).filter((p) => p.props.accessibilityRole === 'button');
  act(() => rows[0].props.onPress());
  expect(textOf(tree)).toContain('Invertido $450.00 · Entrada prom. $180.00 · Resultado +$50.00 · Hoy +0.40%');

  const closedTab = tree.root.findAllByType(Pressable).find((p) => p.props.accessibilityRole === 'tab' && !p.props.accessibilityState.selected)!;
  act(() => closedTab.props.onPress());
  expect(textOf(tree)).toContain('Sin posiciones cerradas');
});

test('own hidden profile shows the switch and the hidden note', () => {
  const onToggle = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(
      <CommunityPortfolioSection
        portfolio={{ ...base, isSelf: true, hidden: true, presaleConfio: '1000.00', presaleInvestedUsd: '25.00' }}
        onToggleHidden={onToggle}
      />,
    );
  });
  const text = textOf(tree);
  expect(text).toContain('Así te ven en Comunidad');
  expect(text).toContain('Oculto: nadie más ve tu perfil de inversor.');
  expect(text).toContain('1,000 CONFIO');
  expect(text).toContain('US$25.00 invertidos');
  const toggle = tree.root.findByType(Switch);
  expect(toggle.props.value).toBe(true);
  act(() => toggle.props.onValueChange(false));
  expect(onToggle).toHaveBeenCalledWith(false);
});

test('Bitcoin & gold get their own row; never a $0 row, never on an older server', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CommunityPortfolioSection portfolio={{ ...base, cryptoUsd: '0.99' }} />); });
  expect(textOf(tree)).toContain('Oro y Bitcoin');
  expect(textOf(tree)).toContain('$0.99');
  for (const cryptoUsd of ['0.00', null, undefined]) {
    act(() => { tree.update(<CommunityPortfolioSection portfolio={{ ...base, cryptoUsd }} />); });
    expect(textOf(tree)).not.toContain('Oro y Bitcoin');
  }
});

test('iOS binary: the same amount under "Otros", so the profile still adds up', () => {
  mockFeatures.DEX_TRADING_UI_ENABLED = false;
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CommunityPortfolioSection portfolio={{ ...base, cryptoUsd: '0.99' }} />); });
  expect(textOf(tree)).toContain('Otros');
  expect(textOf(tree)).toContain('$0.99');
  expect(textOf(tree)).not.toContain('Oro y Bitcoin');
});

test('Futuros get their own row; never a $0 row, never on an older server', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CommunityPortfolioSection portfolio={{ ...base, perpsUsd: '107.27' }} />); });
  expect(textOf(tree)).toContain('Futuros');
  expect(textOf(tree)).toContain('$107.27');
  for (const perpsUsd of ['0.00', null, undefined]) {
    act(() => { tree.update(<CommunityPortfolioSection portfolio={{ ...base, perpsUsd }} />); });
    expect(textOf(tree)).not.toContain('Futuros');
  }
});

test('iOS binary: no Futuros row, their value joins "Otros"', () => {
  mockFeatures.DEX_TRADING_UI_ENABLED = false;
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<CommunityPortfolioSection portfolio={{ ...base, cryptoUsd: '0.99', perpsUsd: '107.27' }} />); });
  expect(textOf(tree)).not.toContain('Futuros');
  expect(textOf(tree)).toContain('Otros');
  expect(textOf(tree)).toContain('$108.26');
  act(() => { tree.update(<CommunityPortfolioSection portfolio={{ ...base, perpsUsd: '107.27' }} />); });
  expect(textOf(tree)).toContain('$107.27');
});

test('iOS binary: only certain stock rows in Abiertas and Cerradas, even from an older server', () => {
  mockFeatures.DEX_TRADING_UI_ENABLED = false;
  const { isBundledStockRow } = require('../CommunityPortfolioSection');
  expect(isBundledStockRow('TSLA', 'Tesla')).toBe(true);
  expect(isBundledStockRow('TSLA', 'TSLA · Largo 5x')).toBe(false);   // a Futuros label
  expect(isBundledStockRow('BTC', 'Bitcoin')).toBe(false);            // not an Ondo stock
  expect(isBundledStockRow('NEAR', 'NEAR')).toBe(false);              // a crypto symbol too: unsure, left out
});

describe('positionDestination', () => {
  const { positionDestination } = require('../CommunityPortfolioSection');
  it('opens the stock page for an Ondo token and the asset page for Bitcoin & gold', () => {
    expect(positionDestination({ symbol: 'PBRon', ticker: 'PBR' })).toEqual({ route: 'StockDetail', params: { ticker: 'PBR' } });
    expect(positionDestination({ symbol: 'BTCB', ticker: 'BTC' })).toEqual({ route: 'CryptoDetail', params: { symbol: 'BTCB' } });
    expect(positionDestination({ symbol: 'TON', ticker: 'TON' })).toEqual({ route: 'CryptoDetail', params: { symbol: 'TON' } });
    expect(positionDestination({ symbol: '', ticker: 'X' })).toBeNull();
  });
  it('iOS binary: a stock still opens, a Bitcoin or gold row has no page to open', () => {
    mockFeatures.DEX_TRADING_UI_ENABLED = false;
    expect(positionDestination({ symbol: 'PBRon', ticker: 'PBR' })).toEqual({ route: 'StockDetail', params: { ticker: 'PBR' } });
    expect(positionDestination({ symbol: 'BTCB', ticker: 'BTC' })).toBeNull();
  });
});
