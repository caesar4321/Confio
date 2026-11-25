// A search across stores in the chat: offers of several stores, each with whether Confío can pay it.
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const ID = '7a1c2e3d-4b5f-4a6b-8c9d-0e1f2a3b4c5d';
let mockOffers: any;
let mockFails = false;
const mockQuery = jest.fn(async (_options: any) => {
  if (mockFails) {
    throw new Error('Cannot query field "agentOffers" on type "Query".');
  }
  return { data: { agentOffers: mockOffers } };
});
const mockMutate = jest.fn();
const mockClient = { query: (o: any) => mockQuery(o), mutate: (o: any) => mockMutate(o) };

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray, ...v: unknown[]) => s.reduce((out, part, i) => out + part + (v[i] ?? ''), ''),
  useApolloClient: () => mockClient,
}));

import { PurchaseCards } from '../PurchaseCards';
import { forgetCards, offersActions } from '../helpers';

const offer = (over: any = {}) => ({
  title: 'Audífonos Sony WH-CH520', price: '$899.00', image: 'https://encrypted-tbn1.gstatic.com/a', rating: '4.6',
  reviews: '708', store: 'Walmart México', site: 'walmart.com.mx', pay: 'confio', payText: 'Confío la paga', ...over,
});
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
// One per offer: the outermost element with that label (a Pressable and what it renders share it).
const buttons = (tree: renderer.ReactTestRenderer) => {
  const found = tree.root.findAll((n) => typeof n.props.accessibilityLabel === 'string'
    && n.props.accessibilityLabel.startsWith('Comprar aquí') && typeof n.props.onPress === 'function');
  return found.filter((n, i) => found.findIndex((m) => m.props.accessibilityLabel === n.props.accessibilityLabel) === i);
};

let trees: renderer.ReactTestRenderer[] = [];
async function mount(actions = [{ type: 'offers', target: ID }]) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<PurchaseCards actions={actions} messageId="m1" createdAt="2026-11-25T12:00:00Z" />);
  });
  trees.push(tree);
  return tree;
}

beforeEach(() => {
  forgetCards();
  mockFails = false;
  mockQuery.mockClear();
  mockMutate.mockReset();
  mockOffers = {
    query: 'audífonos sony', picked: null, offers: [
      offer(),
      offer({ title: 'Audífonos Sony 1000X', price: '$6,835.97', store: 'Coppel', site: 'coppel.com', pay: 'none',
        payText: 'Confío aún no paga esta tienda', rating: '', reviews: '' }),
    ],
  };
});
afterEach(() => {
  trees.forEach((tree) => act(() => tree.unmount()));
  trees = [];
});

test('only offers actions with an id are searches', () => {
  expect(offersActions([{ type: 'offers', target: ID }, { type: 'offers', target: ID }, { type: 'task', target: ID },
    { type: 'offers', target: 'not-an-id' }])).toEqual([ID]);
});

test('each offer shows its product, price, store, stars and whether Confío pays it', async () => {
  const tree = await mount();
  expect(mockQuery.mock.calls[0][0].variables).toEqual({ id: ID });
  const all = texts(tree);
  expect(all).toEqual(expect.arrayContaining(['Audífonos Sony WH-CH520', '$899.00', 'Walmart México', '★ 4.6 (708)',
    'Confío la paga', 'Audífonos Sony 1000X', 'Coppel', 'Confío aún no paga esta tienda']));
  expect(buttons(tree)).toHaveLength(2);
  // No stars are drawn when the store shows none.
  expect(all.filter((t) => t.startsWith('★'))).toHaveLength(1);
});

test('Comprar aquí starts the purchase at that store, once', async () => {
  mockMutate.mockResolvedValue({ data: { buyAgentOffer: { success: true, errors: [], task: { id: 'x', site: 'coppel.com' } } } });
  const tree = await mount();
  await act(async () => { buttons(tree)[1].props.onPress(); });
  expect(mockMutate).toHaveBeenCalledTimes(1);
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, index: 1 });
  expect(texts(tree)).toEqual(expect.arrayContaining(['Comprando aquí', 'Empecé la compra en coppel.com. Síguela abajo.']));
  // That one is under way; another may still be picked instead (the new purchase replaces it).
  expect(buttons(tree).map((b) => b.props.disabled)).toEqual([false, true]);
});

test('a refusal is said on the card', async () => {
  mockMutate.mockResolvedValue({ data: { buyAgentOffer: { success: false, errors: ['Ahora hay muchas compras en curso.'] } } });
  const tree = await mount();
  await act(async () => { buttons(tree)[0].props.onPress(); });
  expect(texts(tree)).toContain('Ahora hay muchas compras en curso.');
  expect(buttons(tree)[0].props.disabled).toBe(false);
});

test('an offer already picked is drawn as started', async () => {
  mockOffers = { ...mockOffers, picked: 0 };
  const tree = await mount();
  expect(texts(tree)).toContain('Comprando aquí');
});

test('a server without the search draws nothing (the note keeps its words)', async () => {
  mockFails = true;
  const tree = await mount();
  expect(tree.toJSON()).toBeNull();
});

test('a message without offers draws nothing and asks nothing', async () => {
  const tree = await mount([{ type: 'navigate', target: 'home' }]);
  expect(tree.toJSON()).toBeNull();
  expect(mockQuery).not.toHaveBeenCalled();
});
