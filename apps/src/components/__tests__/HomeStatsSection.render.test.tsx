import React from 'react';
import renderer, { ReactTestInstance, ReactTestRenderer, act } from 'react-test-renderer';
import {AppState, type AppStateStatus} from 'react-native';

const statsSummary = {
  totalUsers: 12345,
  diditVerifiedUsers: 987,
  totalValueLocked: 54321,
  usdyReserve: 1000,
  presaleCusdRaised: 6789,
  ondoStocksTvl: 4321,
};
const mockNavigate = jest.fn();
const mockRefetch = jest.fn(() => Promise.resolve());
const mockRemoveAppStateListener = jest.fn();
const mockUseQuery = jest.fn(
  (_query: any, _options: any): {
    data: {statsSummary: typeof statsSummary} | undefined;
    refetch: typeof mockRefetch;
  } => ({
    data: {statsSummary},
    refetch: mockRefetch,
  }),
);
let appStateHandler: ((state: AppStateStatus) => void) | undefined;
jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
  appStateHandler = handler;
  return {remove: mockRemoveAppStateListener} as any;
});

jest.mock('@apollo/client', () => ({
  useQuery: (query: any, options: any) => mockUseQuery(query, options),
  gql: (s: TemplateStringsArray) => s,
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate }),
}));
jest.mock('../../hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { thousandsSeparator: '.', decimalSeparator: ',' } }),
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../apollo/queries', () => ({ GET_STATS_SUMMARY: 'GET_STATS_SUMMARY' }));

import { HomeStatsSection } from '../HomeStatsSection';

// A TouchableOpacity surfaces through several composite+host layers that all
// carry the same props, so count DISTINCT accessibility labels instead of
// nodes — that is the thing a screen reader (and the user) actually sees.
const tileLabels = (root: ReactTestInstance): string[] => {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const node of root.findAll(n => n.props?.accessibilityRole === 'button')) {
    const label = node.props.accessibilityLabel as string | undefined;
    if (!label || seen.has(label)) continue;
    seen.add(label);
    ordered.push(label);
  }
  return ordered;
};

const render = (showStocks: boolean): ReactTestRenderer => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(<HomeStatsSection showStocks={showStocks} />);
  });
  return tree;
};

describe('HomeStatsSection layout', () => {
  beforeEach(() => {
    mockRefetch.mockClear();
    mockRemoveAppStateListener.mockClear();
    appStateHandler = undefined;
  });

  it('lays 4 tiles out as 2 rows of 2, all rendered', () => {
    const tree = render(true);
    // Every tile is really in the tree — nothing clipped or scrolled away.
    const labels = tileLabels(tree.root);
    expect(labels).toHaveLength(4);
    expect(labels[0]).toMatch(/^Usuarios/);
    expect(labels[1]).toMatch(/^Ahorros/);
    expect(labels[2]).toMatch(/^Acciones/);
    // Proof before offer: the ask must not outrank the trust numbers.
    expect(labels[3]).toMatch(/^Preventa/);

    // No horizontally scrolling container anywhere in the grid.
    expect(tree.root.findAll(n => n.props?.horizontal === true)).toHaveLength(0);
  });

  it('keeps the single-row strip when stocks are off', () => {
    const tree = render(false);
    expect(tileLabels(tree.root)).toHaveLength(3);
  });

  it('formats values with the locale separator', () => {
    const tree = render(true);
    const usuarios = tileLabels(tree.root)[0];
    expect(usuarios).toContain('12.345');
  });

  it('never presents missing network data as zero savings', () => {
    mockUseQuery.mockImplementationOnce(() => ({
      data: undefined,
      refetch: mockRefetch,
    }));

    const ahorros = tileLabels(render(true).root)[1];
    expect(ahorros).toContain('— USD');
    expect(ahorros).not.toContain('0 USD');
  });

  it('labels the stock figure as current market value rather than cost basis', () => {
    const acciones = tileLabels(render(true).root)[2];
    expect(acciones).toContain('Valor de mercado');
    expect(acciones).not.toContain('Valor invertido');
  });

  it('refreshes marked-to-market stats on the server snapshot cadence', () => {
    render(true);
    expect(mockUseQuery).toHaveBeenCalledWith(
      'GET_STATS_SUMMARY',
      expect.objectContaining({
        fetchPolicy: 'network-only',
        nextFetchPolicy: 'network-only',
        pollInterval: 300_000,
      }),
    );
  });

  it('refetches the universal snapshot after returning to the foreground', async () => {
    render(true);

    await act(async () => {
      appStateHandler?.('background');
      appStateHandler?.('active');
    });

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });

  it('removes the foreground listener when the section unmounts', () => {
    const tree = render(true);

    act(() => tree.unmount());

    expect(mockRemoveAppStateListener).toHaveBeenCalledTimes(1);
  });
});
