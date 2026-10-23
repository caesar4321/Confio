import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../contexts/CountryContext', () => ({ useCountry: () => ({ userCountry: null }) }));
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ replace: jest.fn(), setOptions: jest.fn() }),
  useRoute: () => ({ params: { productId: '7' } }),
}));
const mockQuote = { current: null as any };
const mockRequote = jest.fn(() => Promise.resolve());
jest.mock('@apollo/client', () => {
  const product = { data: { marketplaceProduct: {
    id: '7', title: 'Samsung Teléfono', stock: 1,
    store: { id: '1', name: 'Tienda', city: 'La Paz', countryCode: 'BO', shipsOutsideCity: false },
  } } };
  return {
    gql: () => ({}),
    useQuery: (_q: any, opts: any) => {
      if (opts?.variables?.deliveryCity !== undefined) {
        return { data: mockQuote.current ? { marketCheckoutQuote: mockQuote.current } : undefined, loading: false, refetch: mockRequote };
      }
      if (opts?.skip) return { data: undefined };
      return product;
    },
  };
});
jest.mock('../../services/comprar', () => {
  const actual = jest.requireActual('../../services/comprar');
  return { ...actual, placeMarketOrder: jest.fn() };
});

import { MarketCheckoutScreen } from '../MarketCheckoutScreen';

const QUOTE = { unitPriceUsd: '508.00', amountUsd: '508.00', referenceLocal: null, deliveryCurrency: 'BOB',
  outsideCity: false, shipsOutsideCity: false, deliveryEstimateLocal: '15.00', deliveryPartner: 'Yango Envío' };

const render = () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MarketCheckoutScreen />); });
  return tree;
};
const byId = (tree: renderer.ReactTestRenderer, id: string) => tree.root.findAll((n) => n.props.testID === id)[0];
const input = (tree: renderer.ReactTestRenderer, placeholder: string) =>
  tree.root.findAll((n) => n.props.placeholder === placeholder && typeof n.props.onChangeText === 'function')[0];
const blocker = (tree: renderer.ReactTestRenderer) => {
  const node = byId(tree, 'checkout-blocker');
  return node ? String(node.props.children) : null;
};

beforeEach(() => { mockQuote.current = QUOTE; mockRequote.mockClear(); });

it('says what is missing until the form can pay, then enables Pagar', () => {
  const tree = render();
  expect(byId(tree, 'checkout-pay').props.disabled).toBe(true);
  expect(blocker(tree)).toContain('dirección');
  act(() => { input(tree, 'Dirección (calle, número, zona)').props.onChangeText('Av. Arce 2345, Sopocachi'); });
  expect(blocker(tree)).toContain('teléfono');
  act(() => { input(tree, 'Teléfono para el repartidor').props.onChangeText('70000000'); });
  expect(blocker(tree)).toBeNull();
  expect(byId(tree, 'checkout-pay').props.disabled).toBe(false);
});

it('offers a retry when the total could not be calculated', () => {
  mockQuote.current = null;
  const tree = render();
  expect(blocker(tree)).toContain('No pudimos calcular el total');
  act(() => { byId(tree, 'checkout-requote').props.onPress(); });
  expect(mockRequote).toHaveBeenCalled();
});

it('blocks the screen while paying, but steps aside for Confío Face', async () => {
  const { placeMarketOrder } = require('../../services/comprar');
  let stageCb: (s: string) => void = () => {};
  placeMarketOrder.mockImplementation((_i: any, _c: any, onStage: any) => { stageCb = onStage; return new Promise(() => {}); });
  const tree = render();
  act(() => { input(tree, 'Dirección (calle, número, zona)').props.onChangeText('Av. Arce 2345, Sopocachi'); });
  act(() => { input(tree, 'Teléfono para el repartidor').props.onChangeText('70000000'); });
  const blocking = () => tree.root.findAll((n) => n.props.testID === 'comprar-blocking');
  await act(async () => { byId(tree, 'checkout-pay').props.onPress(); });
  act(() => { stageCb('preparing'); });
  expect(blocking().length).toBeGreaterThan(0);
  act(() => { stageCb('face'); });
  expect(blocking().length).toBe(0); // gone at once: Face presents over nothing
  act(() => { stageCb('paying'); });
  expect(blocking().length).toBeGreaterThan(0);
  expect(JSON.stringify(tree.toJSON())).toContain('Pagando US$');
});
