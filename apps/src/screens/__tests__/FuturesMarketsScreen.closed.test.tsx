import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockUsePositions = jest.fn();
let mockPositions: any[] = [];

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ goBack: jest.fn(), navigate: mockNavigate }),
  useFocusEffect: () => {},
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/VenueAttribution', () => ({ VenueAttribution: 'VenueAttribution' }));
jest.mock('../../components/futures/PerpMarketMark', () => ({ PerpMarketMark: 'PerpMarketMark' }));
jest.mock('../../hooks/useGmMarket', () => ({ useGmMarket: () => ({ stocks: [] }) }));
jest.mock('../../hooks/useLiveMids', () => ({ useLiveMids: () => ({}) }));
jest.mock('../../hooks/usePerps', () => ({
  usePerpsCapabilities: () => ({ capabilities: { enabled: true }, loading: false }),
  usePerpsMarkets: () => ({ markets: [], loading: false, refetch: () => Promise.resolve() }),
  usePerpsPositions: (...a: any[]) => {
    mockUsePositions(...a);
    return { positions: mockPositions, unknown: false, refetch: () => Promise.resolve() };
  },
}));

import { FuturesMarketsScreen } from '../FuturesMarketsScreen';

const position = (over: any) => ({
  id: '1', coin: 'BTC', ticker: 'BTC', name: 'Bitcoin', side: 'long', leverage: 5, state: 'done',
  marginUsd: 10, putInUsd: 10, resultUsd: 2, liquidation: null, doneAt: '2026-10-20T15:00:00Z',
  nextAction: null, marginUsedUsd: null, returnOnEquity: null, unrealizedPnlUsd: null,
  ...over,
});

const render = () => {
  let tree: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<FuturesMarketsScreen />); });
  return tree!;
};
const byTestId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((n) => n.props.testID === id && typeof n.type !== 'string');

describe('FuturesMarketsScreen closed positions', () => {
  beforeEach(() => { mockNavigate.mockClear(); mockUsePositions.mockClear(); });

  it('asks for live positions and one more closed one than it shows', () => {
    mockPositions = [];
    render();
    expect(mockUsePositions).toHaveBeenCalledWith(true, { doneLimit: 11 });
  });

  it('shows ten closed positions, then ten more on Ver más', () => {
    mockPositions = Array.from({ length: 11 }, (_, i) =>
      position({ id: `p${i}`, doneAt: `2026-10-${String(20 - i).padStart(2, '0')}T12:00:00Z` }));
    const tree = render();
    act(() => { byTestId(tree, 'futures-closed-toggle')[0].props.onPress(); });
    expect(byTestId(tree, 'futures-closed-p9').length).toBeGreaterThan(0);
    expect(byTestId(tree, 'futures-closed-p10')).toHaveLength(0);
    act(() => { byTestId(tree, 'futures-closed-more')[0].props.onPress(); });
    expect(mockUsePositions).toHaveBeenLastCalledWith(true, { doneLimit: 21 });
    expect(byTestId(tree, 'futures-closed-p10').length).toBeGreaterThan(0);
    expect(byTestId(tree, 'futures-closed-more')).toHaveLength(0);
  });

  it('lists only real results, newest first, behind a toggle that opens the position', () => {
    mockPositions = [
      position({ id: 'old', ticker: 'ETH', doneAt: '2026-10-01T12:00:00Z' }),
      position({ id: 'new', ticker: 'BTC', doneAt: '2026-10-20T12:00:00Z', resultUsd: -3 }),
      position({ id: 'refunded', ticker: 'SOL', resultUsd: null }),
      position({ id: 'failed', ticker: 'XRP', state: 'failed', resultUsd: null }),
      position({ id: 'open', ticker: 'GOLD', state: 'open', resultUsd: null }),
    ];
    const tree = render();
    expect(byTestId(tree, 'futures-closed-old')).toHaveLength(0);
    act(() => { byTestId(tree, 'futures-closed-toggle')[0].props.onPress(); });
    const rows = tree.root.findAll((n) => typeof n.props.testID === 'string'
      && n.props.testID.startsWith('futures-closed-') && n.props.testID !== 'futures-closed-toggle'
      && typeof n.type !== 'string');
    // Each row shows up once per wrapper component; the order is what counts.
    expect([...new Set(rows.map((r) => r.props.testID))]).toEqual(['futures-closed-new', 'futures-closed-old']);
    // A failed open is neither closed nor a live chip.
    expect(tree.root.findAll((n) => n.props.ticker === 'XRP')).toHaveLength(0);
    act(() => { rows[0].props.onPress(); });
    expect(mockNavigate).toHaveBeenCalledWith('FuturesPosition', { positionId: 'new' });
  });

  it('says so when the server cap is reached instead of offering more', () => {
    mockPositions = Array.from({ length: 200 }, (_, i) => position({ id: `c${i}` }));
    const tree = render();
    act(() => { byTestId(tree, 'futures-closed-toggle')[0].props.onPress(); });
    for (let i = 0; i < 19; i += 1) act(() => { byTestId(tree, 'futures-closed-more')[0].props.onPress(); });
    expect(mockUsePositions).toHaveBeenLastCalledWith(true, { doneLimit: 200 });
    expect(byTestId(tree, 'futures-closed-more')).toHaveLength(0);
    const said = tree.root.findAll((n) => typeof n.props.children !== 'undefined')
      .some((n) => [].concat(n.props.children).join('') === 'Mostramos tus 200 posiciones cerradas más recientes.');
    expect(said).toBe(true);
  });

  it('shows no section without a closed result', () => {
    mockPositions = [position({ id: 'open', state: 'open', resultUsd: null })];
    const tree = render();
    expect(byTestId(tree, 'futures-closed-toggle')).toHaveLength(0);
  });

  it('marks a liquidation instead of a date', () => {
    mockPositions = [position({ id: 'liq', liquidation: 'liquidated', resultUsd: -10 })];
    const tree = render();
    act(() => { byTestId(tree, 'futures-closed-toggle')[0].props.onPress(); });
    expect(byTestId(tree, 'futures-closed-liq')[0].props.accessibilityLabel).toContain('Liquidada');
  });
});
