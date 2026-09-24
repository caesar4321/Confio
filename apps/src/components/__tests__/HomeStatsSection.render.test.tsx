import React from 'react';
import renderer, { ReactTestInstance, ReactTestRenderer, act } from 'react-test-renderer';
import {AppState, type AppStateStatus} from 'react-native';

const statsSummary = {
  totalUsers: 12345,
  diditVerifiedUsers: 987,
  totalValueLocked: 54321,
  cusdBscReserve: 500,
  usdyReserve: 1000,
  presaleCusdRaised: 6789,
  ondoStocksTvl: 4321,
};
const mockNavigate = jest.fn();
const mockRefetch = jest.fn(() => Promise.resolve());
const mockRemoveAppStateListener = jest.fn();
const mockFlow = {totalUsd: 176000, operationCount: 337};
const mockFlowRefetch = jest.fn(() => Promise.resolve());
let mockStockTile: {assetCount: number | null; investedUsd: number | null} | null = {assetCount: 458, investedUsd: null};
const mockUseQuery = jest.fn(
  (query: any, _options: any): any => {
    if (String(query).includes('FundFlowStats')) return {data: {fundFlowStats: mockFlow}, refetch: mockFlowRefetch};
    if (String(query).includes('GmHomeTile')) return {data: {gmHomeTile: mockStockTile}, refetch: jest.fn(() => Promise.resolve())};
    return {data: {statsSummary}, refetch: mockRefetch};
  },
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
  for (const node of root.findAll(n => ['button', 'text'].includes(n.props?.accessibilityRole) && !!n.props?.accessibilityLabel)) {
    const label = node.props.accessibilityLabel as string | undefined;
    if (!label || seen.has(label)) continue;
    seen.add(label);
    ordered.push(label);
  }
  return ordered;
};

const render = (): ReactTestRenderer => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(<HomeStatsSection />);
  });
  return tree;
};

describe('HomeStatsSection layout', () => {
  beforeEach(() => {
    mockRefetch.mockClear();
    mockRemoveAppStateListener.mockClear();
    appStateHandler = undefined;
  });

  it('lays 5 tiles out as a proof row of 3 over an offers row of 2', () => {
    const tree = render();
    // Every tile is really in the tree — nothing clipped or scrolled away.
    const labels = tileLabels(tree.root);
    expect(labels.map(l => l.split(':')[0])).toEqual(
      ['Usuarios', 'Ahorros', 'Movido', 'Acciones', 'Preventa']);
    expect(labels[3]).toContain('Acciones: 458.');
    // Third-width proof cells split label and descriptor onto two lines;
    // the half-width offers row keeps them merged on one.
    const texts = tree.root.findAllByType('Text' as any).map(t => [].concat(t.props.children).join(''));
    expect(texts).toContain('Movido');
    expect(texts).toContain('337 depósitos y retiros');
    expect(texts.some(t => t.startsWith('Preventa'))).toBe(true);
    // Chevrons only in the half-width offers row: in third-width cells they
    // cost the room that kept "6.789 USD" from truncating to "6.789…".
    const chevrons = tree.root.findAll(n => n.type === ('Icon' as any) && n.props.name === 'chevron-right');
    expect(chevrons).toHaveLength(2);

    // No horizontally scrolling container anywhere in the grid.
    expect(tree.root.findAll(n => n.props?.horizontal === true)).toHaveLength(0);
  });

  it('drops Acciones (back to 2x2) for users outside stock eligibility', () => {
    mockStockTile = null;
    const labels = tileLabels(render().root);
    expect(labels.map(l => l.split(':')[0])).toEqual(['Usuarios', 'Ahorros', 'Movido', 'Preventa']);
    mockStockTile = {assetCount: 458, investedUsd: null};
  });

  it('shows the invested total once the server says it is meaningful', () => {
    mockStockTile = {assetCount: 458, investedUsd: 25000};
    const acciones = tileLabels(render().root)[3];
    expect(acciones).toContain('25.000 USD');
    expect(acciones).toContain('Invertido en EE.UU.');
    mockStockTile = {assetCount: 458, investedUsd: null};
  });

  it('shows money moved both ways as a read-only stat', () => {
    const root = render().root;
    const movido = tileLabels(root)[2];
    expect(movido).toContain('176.000 USD');
    expect(movido).toContain('337 depósitos y retiros');
    const node = root.findAll(n => n.props?.accessibilityLabel === movido)[0];
    expect(node.props.accessibilityRole).toBe('text');
    expect(node.props.disabled).toBe(true);
  });

  it('formats values with the locale separator', () => {
    const tree = render();
    const usuarios = tileLabels(tree.root)[0];
    expect(usuarios).toContain('12.345');
  });

  it('never presents missing network data as zero savings', () => {
    mockUseQuery.mockImplementationOnce(() => ({
      data: undefined,
      refetch: mockRefetch,
    }));

    const ahorros = tileLabels(render().root)[1];
    expect(ahorros).toContain('— USD');
    expect(ahorros).not.toContain('0 USD');
  });

  it('does not understate savings when one reserve read is unavailable', () => {
    mockUseQuery.mockImplementationOnce(() => ({
      data: {
        statsSummary: {
          ...statsSummary,
          usdyReserve: null,
        },
      },
      refetch: mockRefetch,
    } as any));

    const ahorros = tileLabels(render().root)[1];
    expect(ahorros).toContain('— USD');
    expect(ahorros).not.toContain('54.821 USD');
  });

  it('reads the cumulative flow from cache, then the network', () => {
    render();
    const options = mockUseQuery.mock.calls.find(([q]) => String(q).includes('FundFlowStats'))?.[1];
    expect(options.fetchPolicy).toBe('cache-and-network');
    expect(options.pollInterval).toBe(600_000);
  });

  it('refreshes marked-to-market stats on the server snapshot cadence', () => {
    render();
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
    render();

    await act(async () => {
      appStateHandler?.('background');
      appStateHandler?.('active');
    });

    expect(mockRefetch).toHaveBeenCalledTimes(1);
  });

  it('removes the foreground listener when the section unmounts', () => {
    const tree = render();

    act(() => tree.unmount());

    expect(mockRemoveAppStateListener).toHaveBeenCalledTimes(1);
  });
});
