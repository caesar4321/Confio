import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../contexts/CountryContext', () => ({ useCountry: () => ({ userCountry: null }) }));
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/common/SuccessHero', () => ({ SuccessHero: 'SuccessHero' }));
jest.mock('../../components/common/ProcessingHero', () => ({ ProcessingHero: 'ProcessingHero' }));
const mockParams = { current: {} as any };
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ replace: jest.fn(), navigate: jest.fn(), setOptions: jest.fn() }),
  useRoute: () => ({ params: mockParams.current }),
}));
const mockOrder = { current: null as any };
const mockRate = jest.fn((..._args: any[]) => Promise.resolve({ data: { rateMarketOrder: { success: true } } }));
jest.mock('@apollo/client', () => ({
  gql: () => ({}),
  useQuery: () => ({ data: { marketOrder: mockOrder.current }, loading: false, refetch: jest.fn(), startPolling: jest.fn(), stopPolling: jest.fn() }),
  useMutation: () => [mockRate, { loading: false }],
}));

import { MarketOrderScreen } from '../MarketOrderScreen';

const order = (status: string, actions: string[]) => ({
  id: '9', role: 'buyer', status, pendingAction: null, productId: '7', productTitle: 'Samsung Teléfono',
  productPhotoUrl: null, quantity: 1, amountUsd: '508.00', referenceLocal: null, deliveryCurrency: 'BOB',
  deliveryCity: 'La Paz', deliveryOutsideCity: false, deliveryEstimateLocal: '15.00', deliveryAddress: 'Av. Arce 2345',
  deliveryPhone: '70000000', deliveryNote: '', trackingReference: null, shipBy: '2026-10-26T12:00:00Z',
  releaseAt: null, createdAt: '2026-10-23T12:00:00Z', availableActions: actions, rating: null,
  store: { id: '1', name: 'Tienda De Juli' },
});

const render = () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MarketOrderScreen />); });
  return tree;
};
const action = (tree: renderer.ReactTestRenderer, a: string) =>
  tree.root.findAll((n) => n.props.testID === `order-action-${a}` && n.props.label)[0];

beforeEach(() => { mockParams.current = { orderId: '9' }; });

it('just after paying, the buyer waits for the store: no "Lo recibí" button, a celebration and what comes next', () => {
  mockParams.current = { orderId: '9', justPaid: true };
  mockOrder.current = order('funded', ['confirm', 'dispute']);
  const tree = render();
  expect(tree.root.findAll((n) => n.type === ('SuccessHero' as any)).length).toBe(1);
  expect(JSON.stringify(tree.toJSON())).toContain('Qué sigue');
  expect(action(tree, 'confirm').props.label).toBe('Ya lo recibí');
  expect(action(tree, 'confirm').props.variant).toBe('ghost');
  expect(action(tree, 'dispute').props.label).toBe('Cancelar o reportar un problema');
  expect(tree.root.findAll((n) => n.props.label === 'Seguir comprando').length).toBeGreaterThan(0);
});

it('once shipped, receiving it is the main action', () => {
  mockOrder.current = order('shipped', ['confirm', 'dispute']);
  const tree = render();
  expect(action(tree, 'confirm').props.label).toBe('Lo recibí');
  expect(action(tree, 'confirm').props.variant).toBe('primary');
  expect(action(tree, 'dispute').props.label).toBe('Tengo un problema');
  expect(tree.root.findAll((n) => n.type === ('SuccessHero' as any)).length).toBe(0);
});

it('does not wrap the shared header in a second top safe area', () => {
  mockOrder.current = order('shipped', []);
  const tree = render();
  expect(tree.root.findAll((n) => n.type === ('SafeAreaView' as any)).length).toBe(0);
});


it('a delivered order invites a written review, sends it with the stars and says it will be published after review', async () => {
  mockOrder.current = order('released', []);
  const tree = render();
  const star4 = tree.root.findAll((n) => n.props.accessibilityLabel === '4 estrellas' && n.props.onPress)[0];
  act(() => { star4.props.onPress(); });
  const box = tree.root.findAll((n) => n.props.testID === 'review-text' && n.props.onChangeText)[0];
  act(() => { box.props.onChangeText('Muy buena atención, volvería a comprar.'); });
  const submit = tree.root.findAll((n) => n.props.testID === 'review-submit' && n.props.label)[0];
  expect(submit.props.label).toBe('Publicar opinión');
  await act(async () => { submit.props.onPress(); });
  expect(mockRate).toHaveBeenCalledWith({ variables: { orderId: '9', rating: 4, comment: 'Muy buena atención, volvería a comprar.' } });
  expect(JSON.stringify(tree.toJSON())).toContain('La publicaremos en la tienda en cuanto la revisemos');
});

it("the seller opens the buyer's pin straight in Yango, falling back to maps", async () => {
  const { Linking } = require('react-native');
  const open = jest.spyOn(Linking, 'openURL').mockImplementationOnce(() => Promise.reject(new Error('no app')))
    .mockImplementation(() => Promise.resolve(true));
  mockOrder.current = { ...order('funded', ['ship']), role: 'merchant', deliveryLatitude: -16.4955, deliveryLongitude: -68.1336,
    deliveryNote: 'Puerta verde', buyerDisplayName: 'ana' };
  const tree = render();
  const yango = tree.root.findAll((n) => n.props.testID === 'order-open-yango' && n.props.label)[0];
  await act(async () => { yango.props.onPress(); });
  expect(open.mock.calls[0][0]).toBe('yango://route?end-lat=-16.495500&end-lon=-68.133600');
  expect(String(open.mock.calls[1][0])).toMatch(/geo:|maps:/); // Yango missing: the phone's maps
  open.mockRestore();
});

it('a buyer sees the pin but not the seller tools', () => {
  mockOrder.current = { ...order('funded', []), deliveryLatitude: -16.4955, deliveryLongitude: -68.1336 };
  const tree = render();
  expect(tree.root.findAll((n) => n.props.testID === 'order-delivery-map').length).toBeGreaterThan(0);
  expect(tree.root.findAll((n) => n.props.testID === 'order-open-yango').length).toBe(0);
});
