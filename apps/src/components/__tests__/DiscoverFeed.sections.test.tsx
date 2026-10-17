import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, Pressable, Text } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../ResponsiveImage', () => ({ ResponsiveImage: 'ResponsiveImage' }));
jest.mock('../ContentPoll', () => ({ ContentPoll: () => null }));
jest.mock('../EmptyState', () => ({ EmptyState: 'EmptyState' }));
const mockNavigate = jest.fn();
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
let mockIsEmployee = false;
const mockRampNavigate = jest.fn();
jest.mock('../../hooks/useRampCountry', () => ({ useRampCountry: () => ({ navigateToRampOrEfectivo: mockRampNavigate }) }));
jest.mock('../../contexts/AccountContext', () => ({
  useAccount: () => ({ activeAccount: { isEmployee: mockIsEmployee } }),
}));

import { DISCOVER_SECTIONS, DiscoverFeed, DiscoverItem } from '../DiscoverFeed';

const item = (overrides: Partial<DiscoverItem>): DiscoverItem => ({
  id: 1, type: 'news', tag: 'Producto', tagColor: '#1DB587', title: 'Hola', body: 'Cuerpo', time: '2h',
  ...overrides,
});

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((node) => [node.props.children].flat().join(''));

const render = (props: Partial<React.ComponentProps<typeof DiscoverFeed>>) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<DiscoverFeed items={[]} refreshing={false} {...props} />);
  });
  return tree;
};

describe('DiscoverFeed sections', () => {
  it('shows the source and the Oficial badge only for verified channels', () => {
    const tree = render({
      items: [
        item({ id: 1, sourceName: 'Confío News', isOfficial: true }),
        item({ id: 2, sourceName: 'Café Juan', isOfficial: false }),
      ],
    });
    const shown = texts(tree);
    expect(shown).toContain('Confío News');
    expect(shown).toContain('Café Juan');
    const badges = tree.root.findAll((node) => node.type === Pressable && /Fuente oficial/.test(node.props.accessibilityLabel || ''));
    expect(badges).toHaveLength(1);
    // One byline line: topic and time, no emoji prefix.
    expect(shown).toContain('Producto · 2h');
    // No avatar configured: the channel's initial, skipping emoji and accents' case.
    expect(shown).toContain('C');
  });

  it('explains what Oficial means when the badge is tapped', () => {
    const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    const tree = render({ items: [item({ sourceName: 'CIP Lima', isOfficial: true })] });
    const badge = tree.root.find((node) => node.type === Pressable && /Fuente oficial/.test(node.props.accessibilityLabel || ''));
    act(() => badge.props.onPress());
    expect(alert).toHaveBeenCalledWith('Fuente oficial', expect.stringMatching(/canal de Confío o una organización cuya identidad legal/));
    alert.mockRestore();
  });

  it('offers Para ti, Oficial and Comunidad and reports the pick', () => {
    const onSelectSection = jest.fn();
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'official', onSelectSection });
    const chips = tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityRole === 'tab');
    expect(chips.map((chip) => chip.findByType(Text).props.children)).toEqual(['Para ti', 'Oficial', 'Comunidad']);
    expect(chips.map((chip) => chip.props.accessibilityState.selected)).toEqual([false, true, false]);
    act(() => chips[2].props.onPress());
    expect(onSelectSection).toHaveBeenCalledWith('community');
  });

  it('tells Comunidad readers it is coming, not that the app is empty', () => {
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'community' });
    expect(tree.root.findByType('EmptyState' as any).props.title).toBe('Aún no hay publicaciones');
  });

  it('says the load failed instead of claiming there is nothing', () => {
    const onRetry = jest.fn();
    const tree = render({ sections: DISCOVER_SECTIONS, activeSection: 'official', loadFailed: true, onRetry });
    const empty = tree.root.findByType('EmptyState' as any);
    expect(empty.props.title).toBe('No pudimos cargar Descubrir');
    empty.props.onAction();
    expect(onRetry).toHaveBeenCalled();
  });

  it('shows no chips on a server without sections', () => {
    const tree = render({ items: [item({})] });
    expect(tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityRole === 'tab')).toHaveLength(0);
  });

  it('renders an activity post as the verified movement plus the note, never the body', () => {
    const tree = render({
      items: [item({ id: 7, sourceName: 'ana', body: 'Compró AAPL por US$50\n\nMi primera acción', title: '' })],
      postExtras: {
        7: {
          contentItemId: '7', authorId: '42', note: 'Mi primera acción',
          activity: { kind: 'stock_buy', ticker: 'AAPL', amountUsd: '50.00', headline: 'Compró AAPL por US$50' },
        },
      },
    });
    const shown = texts(tree);
    expect(shown).toContain('Compró AAPL');
    expect(shown).toContain('Mi primera acción');
    expect(shown.some((text) => text.includes('Compró AAPL por US$50'))).toBe(false);
  });

  it('opens the stock or money screen from an activity, by kind', () => {
    const tree = render({
      items: [item({ id: 7, sourceName: 'ana' }), item({ id: 8, sourceName: 'ben' })],
      postExtras: {
        7: { contentItemId: '7', activity: { kind: 'stock_sell', ticker: 'SPY', headline: 'Vendió SPY' } },
        8: { contentItemId: '8', activity: { kind: 'withdraw', rail: 'QR', headline: 'Retiró' } },
      },
    });
    const press = (hint: string) =>
      act(() => tree.root.find((node) => node.type === Pressable && node.props.accessibilityHint === hint).props.onPress());
    const spy = tree.root.find((node) => node.type === Pressable && node.props.accessibilityHint === 'Ver SPY');
    expect(spy.props.accessibilityLabel).toBe('Vendió SPY');
    press('Ver SPY');
    expect(mockNavigate).toHaveBeenLastCalledWith('StockDetail', { ticker: 'SPY' });
    press('Retirar dólares');
    expect(mockRampNavigate).toHaveBeenLastCalledWith('Sell', { destination: 'cusd_plus' });
  });

  it('offers the activity as an accessibility action on the card', () => {
    const tree = render({
      items: [item({ id: 7, sourceName: 'ana' })],
      postExtras: { 7: { contentItemId: '7', activity: { kind: 'stock_buy', ticker: 'NVDA', headline: 'Compró NVDA' } } },
    });
    const card = tree.root.find((node) => node.type === Pressable && node.props.accessibilityHint === 'Abre la publicación');
    expect(card.props.accessibilityActions).toEqual([{ name: 'openActivity', label: 'Ver NVDA' }]);
    act(() => card.props.onAccessibilityAction({ nativeEvent: { actionName: 'openActivity' } }));
    expect(mockNavigate).toHaveBeenLastCalledWith('StockDetail', { ticker: 'NVDA' });
  });

  it('shows a Pay post by the business paid, never a personal merchant, and opens Pagar', () => {
    const tree = render({
      items: [item({ id: 9, sourceName: 'ana' }), item({ id: 10, sourceName: 'ben' })],
      postExtras: {
        9: { contentItemId: '9', activity: { kind: 'pay', merchant: 'Café Luna', amountUsd: '4.50', headline: 'Pagó en Café Luna' } },
        10: { contentItemId: '10', activity: { kind: 'pay', merchant: null, headline: 'Pagó con QR' } },
      },
    });
    const shown = texts(tree);
    expect(shown).toContain('Pagó en Café Luna');
    expect(shown).toContain('Pagó con QR');
    const pay = tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityHint === 'Pagar con QR');
    act(() => pay[0].props.onPress());
    expect(mockNavigate).toHaveBeenLastCalledWith('Scan', { mode: 'pagar' });
  });

  it('labels local transfers by rail and country, never the other side', () => {
    const tree = render({
      items: [item({ id: 11, sourceName: 'ana' }), item({ id: 12, sourceName: 'ben' }), item({ id: 13, sourceName: 'cy' })],
      postExtras: {
        11: { contentItemId: '11', activity: { kind: 'send', local: true, rail: 'Bre-B', country: 'CO', headline: 'x' } },
        12: { contentItemId: '12', activity: { kind: 'receive', local: true, country: 'CO', headline: 'x' } },
        13: { contentItemId: '13', activity: { kind: 'pay', local: true, merchant: null, country: 'AR', headline: 'x' } },
      },
    });
    const shown = texts(tree);
    expect(shown).toContain('Envió por Bre-B');
    expect(shown).toContain('Recibió por su cuenta local');
    expect(shown).toContain('Pagó con QR');
    expect(shown.some((t) => t.includes('Colombia'))).toBe(true);
  });

  it("never sends an employee to the owner's money screens", () => {
    mockIsEmployee = true;
    const tree = render({
      items: [item({ id: 8, sourceName: 'ben' })],
      postExtras: { 8: { contentItemId: '8', activity: { kind: 'top_up', headline: 'Recargó' } } },
    });
    expect(tree.root.findAll((node) => node.type === Pressable && node.props.accessibilityHint === 'Recargar dólares'))
      .toHaveLength(0);
    mockIsEmployee = false;
  });

  it('opens the author profile from a member byline, but not from official ones', () => {
    const onOpenAuthor = jest.fn();
    const tree = render({
      items: [item({ id: 1, sourceName: 'ana' }), item({ id: 2, sourceName: 'Confío', isOfficial: true })],
      postExtras: { 1: { contentItemId: '1', authorId: '42' }, 2: { contentItemId: '2', authorId: '9' } },
      onOpenAuthor,
    });
    const links = tree.root.findAll((node) => node.type === Pressable && /Ver el perfil/.test(node.props.accessibilityLabel || ''));
    expect(links).toHaveLength(1);
    act(() => links[0].props.onPress());
    expect(onOpenAuthor).toHaveBeenCalledWith('42');
  });
});
