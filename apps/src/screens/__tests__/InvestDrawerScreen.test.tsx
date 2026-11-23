// Invertir and Comunidad in the conversation home: two drawer items, one
// screen, no segment bar (docs/designs/ai-assistant-first-redesign.md 7.3).
import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockMarkSeen = jest.fn();
let mockFocused = true;
let mockConversationHome = true;

jest.mock('../../config/features', () => ({
  get CONVERSATION_HOME_ENABLED() { return mockConversationHome; },
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: jest.fn() }),
  useIsFocused: () => mockFocused,
  useFocusEffect: () => {},
}));
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../InvestScreen', () => ({ InvestScreen: 'InvestScreen' }));
jest.mock('../DiscoverScreen', () => ({ DiscoverScreen: 'DiscoverScreen' }));
jest.mock('../../components/CommunityPreviewCard', () => ({ CommunityPreviewCard: 'CommunityPreviewCard' }));
jest.mock('../../components/HomeStatsSection', () => ({ HomeStatsSection: 'HomeStatsSection' }));
jest.mock('../../home/DrawerHeader', () => ({ DrawerHeader: 'DrawerHeader' }));
jest.mock('../../hooks/useSavingsPortfolio', () => ({ useSavingsPortfolio: () => ({ stocks: { enabled: true } }) }));
jest.mock('../../home/useFloatingPrimaryInset', () => ({ useFloatingPrimaryInset: () => 84 }));
jest.mock('../../services/communityPeek', () => ({
  markCommunitySeen: (...args: unknown[]) => mockMarkSeen(...args),
  refreshCommunityPeek: jest.fn(),
  useCommunityPeek: () => ({ unread: 0, neverOpened: false }),
}));

import { InvestTabScreen } from '../InvestTabScreen';

const header = (tree: renderer.ReactTestRenderer) => tree.root.findByType('DrawerHeader' as any).props;
const invest = (tree: renderer.ReactTestRenderer) => tree.root.findByType('InvestScreen' as any).props;
const community = (tree: renderer.ReactTestRenderer) => tree.root.findByType('DiscoverScreen' as any).props;
async function mount(params?: { segment?: 'invest' | 'community'; at?: number }) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestTabScreen route={{ params }} />); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockFocused = true;
  mockConversationHome = true;
});

it('shows one of the two under its own title, with the menu and no segment bar', async () => {
  let tree = await mount({ segment: 'invest', at: 1 });
  expect(header(tree).title).toBe('Invertir');
  expect(tree.root.findAll((n) => n.props.accessibilityRole === 'tablist')).toHaveLength(0);
  // Comunidad has its own entry in the menu: no preview of it on top of Invertir.
  expect(invest(tree).topAccessory).toBeUndefined();
  await act(async () => tree.unmount());

  tree = await mount({ segment: 'community', at: 2 });
  expect(header(tree).title).toBe('Comunidad');
  await act(async () => tree.unmount());
});

it('Comunidad opens with the network figures that left Inicio, drawn as one of its own strips', async () => {
  const tree = await mount({ segment: 'community', at: 1 });
  expect(community(tree).topAccessory.type).toBe('HomeStatsSection');
  expect(community(tree).topAccessory.props.variant).toBe('strip');
  expect(community(tree).topAccessory.props.stocksEnabled).toBe(true);
  expect(community(tree).sections).toEqual(['community']);
  // Room at the end of the feed for the floating Pagar button over it.
  expect(community(tree).bottomInset).toBe(84);
  await act(async () => tree.unmount());
});

it('the menu (or the assistant) switches between the two by name', async () => {
  const tree = await mount({ segment: 'invest', at: 1 });
  await act(async () => { tree.update(<InvestTabScreen route={{ params: { segment: 'community', at: 5 } }} />); });
  expect(header(tree).title).toBe('Comunidad');
  await act(async () => { tree.update(<InvestTabScreen route={{ params: { segment: 'invest', at: 6 } }} />); });
  expect(header(tree).title).toBe('Invertir');
  await act(async () => tree.unmount());
});

it('only posts actually on screen clear the Comunidad badge', async () => {
  const tree = await mount({ segment: 'invest', at: 1 });
  await act(async () => { community(tree).onShown([{ id: '1' }]); });
  expect(mockMarkSeen).not.toHaveBeenCalled();
  await act(async () => { tree.update(<InvestTabScreen route={{ params: { segment: 'community', at: 2 } }} />); });
  expect(mockMarkSeen).toHaveBeenCalledWith([{ id: '1' }]);
  await act(async () => tree.unmount());
});

it('five tabs: the segment bar, unchanged', async () => {
  mockConversationHome = false;
  const tree = await mount();
  expect(tree.root.findAll((n) => n.props.accessibilityRole === 'tablist').length).toBeGreaterThan(0);
  expect(tree.root.findAllByType('DrawerHeader' as any)).toHaveLength(0);
  expect(tree.root.findByType('DiscoverScreen' as any).props.topAccessory).toBeUndefined();
  await act(async () => tree.unmount());
});
