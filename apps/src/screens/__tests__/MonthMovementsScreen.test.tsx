/**
 * "Sin categoría" labels a whole counterparty with one tap; two quick taps
 * must not race (the later-committed write would win over the last choice).
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockCategorize = jest.fn();
const mockRefetch = jest.fn(() => Promise.resolve());
let mockQueryOpts: any;
let mockMutationOpts: any;
const movements = [
  { id: '1', kind: 'p2p_send', direction: 'sent', amountUsd: '4.00', category: null,
    counterpartyKey: 'user:9', counterpartyName: 'Doña Rosa', date: '2026-10-02T10:00:00Z' },
  { id: '2', kind: 'p2p_send', direction: 'sent', amountUsd: '6.00', category: null,
    counterpartyKey: 'user:9', counterpartyName: 'Doña Rosa', date: '2026-10-03T10:00:00Z' },
];

jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useQuery: (_q: any, opts: any) => (mockQueryOpts = opts, { data: { monthMovements: movements }, loading: false, error: undefined, refetch: mockRefetch }),
  useMutation: (_m: any, opts: any) => (mockMutationOpts = opts, [mockCategorize]),
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ goBack: jest.fn() }),
  useRoute: () => ({ params: { year: 2026, month: 10, filterBy: 'uncategorized', title: 'Sin categoría' } }),
}));
jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: ({ children }: any) => children }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../services/analyticsService', () => ({ AnalyticsService: { logFunnelEvent: jest.fn() } }));

import { MonthMovementsScreen } from '../MonthMovementsScreen';

const chip = (tree: renderer.ReactTestRenderer, key: string) =>
  tree.root.findAll(n => n.props.testID === `category-chip-${key}` && typeof n.props.onPress === 'function')[0];

describe('MonthMovementsScreen (Sin categoría)', () => {
  it('groups by counterparty with the total of its payments', () => {
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<MonthMovementsScreen />); });
    const text = tree.root.findAll(n => (n.type as unknown) === 'Text')
      .map(n => [].concat(n.props.children).filter((c: unknown) => typeof c !== 'object').join('')).join('|');
    expect(text).toContain('Doña Rosa');
    expect(text).toContain('2 pagos');
    expect(text).toContain('US$10');
    expect(tree.root.findAllByProps({ testID: 'uncategorized-group-user:9' }).length).toBeGreaterThan(0);
  });

  it('one save at a time: a second tap while saving is ignored', async () => {
    let resolve!: (v: any) => void;
    mockCategorize.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    let tree!: renderer.ReactTestRenderer;
    act(() => { tree = renderer.create(<MonthMovementsScreen />); });
    act(() => { chip(tree, 'food').props.onPress(); });
    expect(chip(tree, 'family').props.disabled).toBe(true);
    act(() => { chip(tree, 'family').props.onPress(); });
    expect(mockCategorize).toHaveBeenCalledTimes(1);
    expect(mockCategorize).toHaveBeenCalledWith({ variables: { movementId: '1', category: 'food', applyTo: 'counterparty' } });
    await act(async () => resolve({ data: { categorizeMovement: { success: true } } }));
    expect(mockRefetch).toHaveBeenCalled();
    // the post-save refetch is a new request, never one sent before the save
    expect(mockQueryOpts.context).toEqual({ queryDeduplication: false });
    // the mounted Tu mes summary is refetched by name, even if the user left mid-save
    expect(mockMutationOpts.refetchQueries).toEqual(['MonthSummary', 'MonthMovements']);
    expect(chip(tree, 'family').props.disabled).toBe(false);
  });
});
