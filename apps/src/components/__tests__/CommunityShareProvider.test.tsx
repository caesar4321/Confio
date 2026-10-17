import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockShareable: any = null;
let mockQueryError: any = null;
let mockAccountType = 'personal';
const mockRefetch = jest.fn().mockResolvedValue({});
const mockShareIntent = jest.fn();
const mockNavigate = jest.fn();

jest.mock('../../hooks/useRampCountry', () => ({ useRampCountry: () => ({ navigateToRampOrEfectivo: jest.fn() }) }));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: jest.fn() }) }));
jest.mock('@apollo/client', () => ({
  useQuery: (query: string, options: any) => {
    if (query === 'GET_SHARE_SHEET_ACTIVITY') {
      return { data: options?.skip ? undefined : { shareableActivity: mockShareable }, loading: false, error: mockQueryError, refetch: mockRefetch };
    }
    return { data: undefined, loading: false, startPolling: jest.fn(), stopPolling: jest.fn() };
  },
  useMutation: () => [mockShareIntent, { loading: false }],
}));
jest.mock('../../apollo/queries', () => ({
  GET_SHARE_SHEET_ACTIVITY: 'GET_SHARE_SHEET_ACTIVITY',
  GET_MY_COMMUNITY_POST: 'GET_MY_COMMUNITY_POST',
  GET_MY_PROFILE_PICTURE: 'GET_MY_PROFILE_PICTURE',
}));
jest.mock('../../apollo/mutations', () => ({ SHARE_ACTIVITY_INTENT: 'SHARE_ACTIVITY_INTENT' }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { type: mockAccountType } }) }));
jest.mock('../../navigation/RootNavigation', () => ({
  navigate: (...args: any[]) => mockNavigate(...args),
  navigationRef: { addListener: () => () => {}, getCurrentRoute: () => undefined },
}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../CommunityRulesSheet', () => ({ CommunityRulesSheet: 'CommunityRulesSheet' }));
jest.mock('../PostByline', () => ({ PostByline: 'PostByline' }));

import { CommunityShareProvider, applyChip, chipsFor, headlineFor } from '../CommunityShareProvider';
import { requestActivityShare, resetActivityShareForTests } from '../../services/communityShare';

const stockBuy = {
  kind: 'stock_buy', date: '2026-10', amountUsd: '25.00', ticker: 'NVDA', name: 'NVIDIA',
  rail: null, country: null, minutes: null, pnlUsd: '1.20', pnlPct: '4.80', position: 'open',
  headline: 'Compró NVDA',
};

const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());
const byTestId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((node) => node.props?.testID === id && typeof node.type !== 'string', { deep: false });

async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<CommunityShareProvider />); });
  return tree;
}

beforeEach(() => {
  resetActivityShareForTests();
  mockShareable = null;
  mockQueryError = null;
  mockAccountType = 'personal';
  mockShareIntent.mockReset();
  mockNavigate.mockReset();
  mockRefetch.mockClear();
});

describe('requestActivityShare', () => {
  it('drops requests without a provider or reference', () => {
    expect(requestActivityShare({ group: 'stock', reference: '0xabc' })).toBe(false);
  });

  it('opens a (group, reference) once per session and one sheet at a time', async () => {
    mockShareable = { unifiedTransactionId: null, pending: true, canShare: true, noteMaxChars: 280, activity: stockBuy };
    const tree = await mount();
    let first = false;
    await act(async () => { first = requestActivityShare({ group: 'stock', reference: '0xabc' }); });
    expect(first).toBe(true);
    // A second request while the sheet is open is dropped (not remembered).
    expect(requestActivityShare({ group: 'send', reference: 'S1' })).toBe(false);
    await act(async () => { byTestId(tree, 'community-share-dismiss')[0].props.onPress(); });
    expect(text(tree)).toBe('null');
    // The same activity never reopens in this session; a new one does.
    expect(requestActivityShare({ group: 'stock', reference: '0xabc' })).toBe(false);
    let next = false;
    await act(async () => { next = requestActivityShare({ group: 'send', reference: 'S1' }); });
    expect(next).toBe(true);
    await act(async () => tree.unmount());
  });

  it('ignores business accounts', async () => {
    mockAccountType = 'business';
    const tree = await mount();
    expect(requestActivityShare({ group: 'stock', reference: '0xabc' })).toBe(false);
    await act(async () => tree.unmount());
  });
});

describe('CommunityShareProvider sheet', () => {
  it('shows nothing when the server has nothing to share', async () => {
    const tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xnull' }); });
    expect(text(tree)).toBe('null');
    await act(async () => tree.unmount());
  });

  it('shows nothing on silent blocks or query errors', async () => {
    mockShareable = { canShare: false, blockCode: 'not_verified', activity: stockBuy };
    let tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xblocked' }); });
    expect(text(tree)).toBe('null');
    await act(async () => tree.unmount());

    mockShareable = { canShare: true, activity: stockBuy };
    mockQueryError = new Error('Cannot query field');
    tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xold-server' }); });
    expect(text(tree)).toBe('null');
    await act(async () => tree.unmount());
  });

  it('shows the preview, chips and live note, then the scheduled copy after Compartir', async () => {
    mockShareable = { unifiedTransactionId: null, pending: true, canShare: true, noteMaxChars: 280, activity: stockBuy };
    mockShareIntent.mockResolvedValue({ data: { shareActivityIntent: { success: true, status: 'scheduled', post: null } } });
    const tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xabc' }); });

    const shown = text(tree);
    expect(shown).toContain('¡Ya tienes NVDA! 🎉');
    expect(shown).toContain('Compró NVDA');
    expect(shown).toContain('US$25.00');
    expect(shown).toContain('Compartir en Comunidad');
    const chips = byTestId(tree, 'community-share-chip');
    expect(chips).toHaveLength(3);

    await act(async () => { chips[0].props.onPress(); });
    expect(byTestId(tree, 'community-share-note')[0].props.value).toBe('📈 A largo plazo');

    // Hiding the amount keeps the percentage.
    await act(async () => { byTestId(tree, 'community-share-show-amount')[0].props.onValueChange(false); });
    expect(text(tree)).not.toContain('US$25.00');
    expect(text(tree)).toContain('+4.80%');

    await act(async () => { byTestId(tree, 'community-share-submit')[0].props.onPress(); });
    expect(mockShareIntent).toHaveBeenCalledWith({
      variables: { group: 'stock', reference: '0xabc', note: '📈 A largo plazo', showAmount: false },
    });
    expect(text(tree)).toContain('Se publicará en cuanto se confirme tu movimiento.');
    await act(async () => tree.unmount());
  });

  it('offers "Ver publicación" when published right away', async () => {
    mockShareable = { unifiedTransactionId: 'U1', pending: false, canShare: true, activity: { ...stockBuy, kind: 'send', headline: 'Envió' } };
    mockShareIntent.mockResolvedValue({ data: { shareActivityIntent: { success: true, status: 'published', post: { id: '42', status: 'APPROVED' } } } });
    const tree = await mount();
    await act(async () => { requestActivityShare({ group: 'send', reference: 'S9' }); });
    expect(text(tree)).toContain('¡Enviado! 💸');
    await act(async () => { byTestId(tree, 'community-share-submit')[0].props.onPress(); });
    expect(text(tree)).toContain('¡Publicado en Comunidad!');
    await act(async () => { byTestId(tree, 'community-share-open-post')[0].props.onPress(); });
    expect(mockNavigate).toHaveBeenCalledWith('Main', { screen: 'DiscoverPostDetail', params: { contentItemId: 42 } });
    expect(text(tree)).toBe('null');
    await act(async () => tree.unmount());
  });

  it('shows server errors inline and keeps the composer', async () => {
    mockShareable = { canShare: true, activity: stockBuy };
    mockShareIntent.mockResolvedValue({ data: { shareActivityIntent: { success: false, error: null, errorCode: 'links' } } });
    const tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xerr' }); });
    await act(async () => { byTestId(tree, 'community-share-submit')[0].props.onPress(); });
    expect(text(tree)).toContain('Las notas no pueden incluir enlaces.');
    expect(text(tree)).toContain('Compartir en Comunidad');
    await act(async () => tree.unmount());
  });

  it('asks for the rules first when required', async () => {
    mockShareable = { canShare: false, blockCode: 'rules_required', activity: stockBuy };
    const tree = await mount();
    await act(async () => { requestActivityShare({ group: 'stock', reference: '0xrules' }); });
    expect(text(tree)).toContain('Lee las normas para compartir');
    await act(async () => { byTestId(tree, 'community-share-submit')[0].props.onPress(); });
    expect(mockShareIntent).not.toHaveBeenCalled();
    expect(tree.root.findByType('CommunityRulesSheet' as any).props.visible).toBe(true);
    await act(async () => tree.unmount());
  });
});

describe('applyChip', () => {
  const chips = ['A', 'B'];
  it('replaces, toggles and appends', () => {
    expect(applyChip('', 'A', chips, 280)).toBe('A');
    expect(applyChip('A', 'B', chips, 280)).toBe('B');
    expect(applyChip('A', 'A', chips, 280)).toBe('');
    expect(applyChip('mi nota', 'A', chips, 280)).toBe('mi nota A');
    expect(applyChip('mi nota', 'A', chips, 8)).toBe('mi nota');
  });
});

describe('Pay in the share sheet', () => {
  it('celebrates the business paid, or just the payment for a personal merchant', () => {
    expect(headlineFor({ kind: 'pay', merchant: 'Café Luna', headline: '' } as any, false)).toBe('¡Pagado en Café Luna! 🛍️');
    expect(headlineFor({ kind: 'pay', merchant: null, headline: '' } as any, false)).toBe('¡Pago listo! 🛍️');
    expect(chipsFor('pay')).toContain('📱 Pagué con QR en segundos');
  });
});
