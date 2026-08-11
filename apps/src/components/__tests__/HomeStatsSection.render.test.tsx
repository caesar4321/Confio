import React from 'react';
import renderer, { ReactTestInstance, ReactTestRenderer, act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const statsSummary = {
  totalUsers: 12345,
  diditVerifiedUsers: 987,
  totalValueLocked: 54321,
  usdyReserve: 1000,
  presaleCusdRaised: 6789,
  ondoStocksTvl: 4321,
};

jest.mock('@apollo/client', () => ({
  useQuery: () => ({ data: { statsSummary }, refetch: jest.fn() }),
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
});
