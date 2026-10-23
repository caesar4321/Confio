import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView', useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/common/SuccessHero', () => ({ SuccessHero: 'SuccessHero' }));
jest.mock('../../components/common/ProcessingHero', () => ({ ProcessingHero: 'ProcessingHero' }));
const mockParams = { current: {} as any };
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ replace: jest.fn(), navigate: jest.fn(), setOptions: jest.fn() }),
  useRoute: () => ({ params: mockParams.current }),
}));
const mockOrder = { current: null as any };
jest.mock('@apollo/client', () => ({
  gql: () => ({}),
  useQuery: () => ({ data: { marketOrder: mockOrder.current }, loading: false, refetch: jest.fn(), startPolling: jest.fn(), stopPolling: jest.fn() }),
  useMutation: () => [jest.fn(), { loading: false }],
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
