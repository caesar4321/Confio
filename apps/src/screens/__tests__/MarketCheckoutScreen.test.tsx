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
const mockBook = { current: [] as any[] };
const mockSaveAddress = jest.fn(() => Promise.resolve({ data: { saveDeliveryAddress: { success: true } } }));
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
      // The address book query: no variables, cache-and-network.
      if (!opts?.variables && opts?.fetchPolicy === 'cache-and-network') {
        return { data: { myDeliveryAddresses: mockBook.current }, loading: false, refetch: jest.fn(() => Promise.resolve()) };
      }
      return product;
    },
    useMutation: () => [mockSaveAddress, { loading: false }],
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

beforeEach(() => { mockQuote.current = QUOTE; mockRequote.mockClear(); mockBook.current = []; mockSaveAddress.mockClear(); });

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


const saved = (over: any = {}) => ({
  id: '3', label: 'Casa', countryCode: 'BO', city: 'La Paz', address: 'Av. Arce 2345, Sopocachi',
  phone: '+59170000000', note: 'Portón verde', isDefault: true, source: 'saved', editable: true, ...over,
});

it('preselects the default address from the book, ready to pay', () => {
  mockBook.current = [saved()];
  const tree = render();
  expect(byId(tree, 'checkout-picked-address')).toBeTruthy();
  expect(input(tree, 'Dirección (calle, número, zona)')).toBeUndefined(); // no typing needed
  expect(blocker(tree)).toBeNull();
  expect(byId(tree, 'checkout-pay').props.disabled).toBe(false);
});

it('never preselects an address in another country', () => {
  mockBook.current = [saved({ countryCode: 'VE', city: 'Caracas' })];
  const tree = render();
  expect(byId(tree, 'checkout-picked-address')).toBeUndefined();
  expect(input(tree, 'Dirección (calle, número, zona)')).toBeTruthy();
});

it('after paying, records the address in the book (used), without waiting on it', async () => {
  const { placeMarketOrder } = require('../../services/comprar');
  placeMarketOrder.mockResolvedValue({ orderId: '9', txHash: '0x1' });
  mockBook.current = [saved()];
  const tree = render();
  await act(async () => { byId(tree, 'checkout-pay').props.onPress(); });
  expect(mockSaveAddress).toHaveBeenCalledWith({ variables: expect.objectContaining({
    address: 'Av. Arce 2345, Sopocachi', city: 'La Paz', countryCode: 'BO', phone: '+59170000000', markUsed: true,
  }) });
});

it("shows the store's delivery inside the total, and another city as coordinated", () => {
  mockQuote.current = { ...QUOTE, productUsd: '508.00', deliveryUsd: '1.30', amountUsd: '509.30' };
  let tree = render();
  let text = JSON.stringify(tree.toJSON());
  expect(text).toContain('Envío en ');
  expect(text).toContain('US$1.30');
  expect(text).toContain('US$509.30');
  expect(text).not.toContain('con tu QR');
  // Another city: the store's other-cities price, inside the total like any delivery.
  mockQuote.current = { ...QUOTE, outsideCity: true, productUsd: '508.00', deliveryUsd: '4.00', amountUsd: '512.00' };
  tree = render();
  text = JSON.stringify(tree.toJSON());
  expect(text).toContain('Envío a ');
  expect(text).toContain('US$512.00');
  expect(text).not.toContain('A coordinar');
});


it('another city with no "other cities" price says the store only delivers in its area', () => {
  mockQuote.current = null; // the server refuses the quote (store_city_only)
  const tree = render();
  const other = tree.root.findAll((n) => n.props.accessibilityRole === 'radio' && n.props.onPress
    && n.props.accessibilityState?.checked === false)[0];
  act(() => { other.props.onPress(); });
  act(() => { input(tree, 'Ciudad de entrega').props.onChangeText('Cochabamba'); });
  expect(blocker(tree)).toContain('solo entrega en La Paz');
  expect(JSON.stringify(tree.toJSON())).not.toContain('Entiendo que el envío');
});

it('an El Alto address priced as the La Paz area is not "another city"', () => {
  mockQuote.current = { ...QUOTE, outsideCity: false, productUsd: '508.00', deliveryUsd: '1.30', amountUsd: '509.30' };
  const tree = render();
  const other = tree.root.findAll((n) => n.props.accessibilityRole === 'radio' && n.props.onPress
    && n.props.accessibilityState?.checked === false)[0];
  act(() => { other.props.onPress(); });
  act(() => { input(tree, 'Ciudad de entrega').props.onChangeText('El Alto'); });
  act(() => { input(tree, 'Dirección (calle, número, zona)').props.onChangeText('Av. 6 de Marzo 100, Ciudad Satélite'); });
  act(() => { input(tree, 'Teléfono para el repartidor').props.onChangeText('70000000'); });
  expect(blocker(tree)).toBeNull(); // the store has no other-cities price, and needs none here
  expect(JSON.stringify(tree.toJSON())).toContain('US$509.30');
});

it('a map pin with a reference replaces the written address, and travels with the payment', async () => {
  const { placeMarketOrder } = require('../../services/comprar');
  placeMarketOrder.mockReset();
  placeMarketOrder.mockResolvedValue({ orderId: '9', txHash: '0x1' });
  const tree = render();
  const picker = tree.root.findAll((n) => typeof n.props.onConfirm === 'function' && n.props.visible !== undefined)[0];
  act(() => { picker.props.onConfirm({ latitude: -16.4955, longitude: -68.1336 }); });
  act(() => { input(tree, 'Teléfono para el repartidor').props.onChangeText('70000000'); });
  expect(blocker(tree)).toContain('referencia');
  const reference = tree.root.findAll((n) => typeof n.props.onChangeText === 'function'
    && String(n.props.placeholder || '').startsWith('Referencia:'))[0];
  act(() => { reference.props.onChangeText('Puerta verde frente a la tienda Rosa'); });
  expect(blocker(tree)).toBeNull();
  await act(async () => { byId(tree, 'checkout-pay').props.onPress(); });
  expect(placeMarketOrder.mock.calls[0][0]).toEqual(expect.objectContaining({
    deliveryAddress: '', deliveryLatitude: -16.4955, deliveryLongitude: -68.1336,
    deliveryNote: 'Puerta verde frente a la tienda Rosa',
  }));
});
