import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {Pressable} from 'react-native';

const mockJoin = jest.fn();
const mockAnswer = jest.fn();
let mockOffers: any[] = [];
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useQuery: () => ({data: {paidOffers: mockOffers}}),
  useMutation: (doc: string) => [doc.includes('joinPaidOfferWaitlist') ? mockJoin : mockAnswer],
}));
const mockGoBack = jest.fn();
let mockParams: any = {offer: 'smart_account', door: 'billeteras'};
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({goBack: mockGoBack}),
  useRoute: () => ({params: mockParams}),
}));
jest.mock('react-native-safe-area-context', () => ({useSafeAreaInsets: () => ({top: 0, bottom: 0, left: 0, right: 0})}));
jest.mock('../../components/svg/CuentaInteligenteMark', () => 'CuentaInteligenteMark');
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../services/analyticsService', () => ({AnalyticsService: {logFunnelEvent: jest.fn()}}));
import {AnalyticsService} from '../../services/analyticsService';
import {PaidOfferScreen} from '../PaidOfferScreen';

const offer = (over: any = {}) => ({
  product: 'smart_account', available: true, rowVisible: true, monthlyPriceUsd: '9.99',
  onWaitlist: false, waitlistedAt: null, wouldPay: null, volumeRange: null, ...over,
});
const texts = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());
const press = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAllByType(Pressable).find(n => n.props.accessibilityLabel === label)!;
let tree: renderer.ReactTestRenderer;
const mount = async () => { await act(async () => { tree = renderer.create(<PaidOfferScreen />); }); };

beforeEach(() => {
  jest.clearAllMocks();
  mockOffers = [offer()];
  mockParams = {offer: 'smart_account', door: 'billeteras'};
});
afterEach(async () => { if (tree) { await act(async () => tree.unmount()); } });

it('shows the matched pitch with the server price and logs the open once', async () => {
  await mount();
  expect(texts(tree)).toContain('Cuenta inteligente');
  expect(texts(tree)).toContain('US$9.99');
  expect(texts(tree)).toContain('/mes al lanzar');
  expect(texts(tree)).toContain('Hoy no se cobra nada');
  const calls = (AnalyticsService.logFunnelEvent as jest.Mock).mock.calls;
  expect(calls).toHaveLength(1);
  expect(calls[0][1]).toMatchObject({stage: 'detail_opened', offer: 'smart_account', door: 'billeteras'});
});

it('hides the price line when the server sends none', async () => {
  mockOffers = [offer({monthlyPriceUsd: null})];
  await mount();
  expect(texts(tree)).not.toContain('US$');
});

it('says ¡Anotado! only after the server confirms the join', async () => {
  let resolve: (v: any) => void = () => {};
  mockJoin.mockReturnValue(new Promise(r => { resolve = r; }));
  await mount();
  await act(async () => { press(tree, 'Sí, avísame').props.onPress(); });
  expect(texts(tree)).not.toContain('Anotado');
  expect(mockJoin).toHaveBeenCalledWith({variables: {product: 'smart_account', door: 'billeteras', trigger: ''}});
  await act(async () => resolve({data: {joinPaidOfferWaitlist: {success: true, waitlistedAt: '2026-10-07T12:00:00Z'}}}));
  expect(texts(tree)).toContain('¡Anotado!');
  expect(texts(tree)).toContain('¿te suscribirías?');
});

it('keeps the button and shows a retry line when the join fails', async () => {
  mockJoin.mockRejectedValue(new Error('offline'));
  await mount();
  await act(async () => { press(tree, 'Sí, avísame').props.onPress(); });
  expect(texts(tree)).not.toContain('Anotado');
  expect(texts(tree)).toContain('No pudimos guardar tu aviso');
  expect(press(tree, 'Sí, avísame')).toBeDefined();
});

it('remembers someone already on the list and asks only what is unanswered', async () => {
  mockOffers = [offer({onWaitlist: true, waitlistedAt: '2026-10-05T12:00:00Z', wouldPay: 'yes'})];
  await mount();
  expect(texts(tree)).toContain('Ya estás en la lista');
  expect(texts(tree)).not.toContain('¿te suscribirías?');
  expect(texts(tree)).toContain('¿Cuánto moverías o guardarías al mes en Confío?');
  mockAnswer.mockResolvedValue({data: {answerPaidOffer: {success: true}}});
  await act(async () => { press(tree, 'US$100 a 500').props.onPress(); });
  expect(mockAnswer).toHaveBeenCalledWith({variables: {product: 'smart_account', volumeRange: '100_500'}});
  expect(texts(tree)).toContain('Listo. Gracias por contarnos.');
});

it('logs Solo miraba and goes back without joining', async () => {
  mockParams = {offer: 'ia_plus', door: 'chip', trigger: 'investing'};
  mockOffers = [offer({product: 'ia_plus'})];
  await mount();
  expect(texts(tree)).toContain('Confío IA+');
  await act(async () => { press(tree, 'Solo miraba').props.onPress(); });
  expect(mockJoin).not.toHaveBeenCalled();
  expect(mockGoBack).toHaveBeenCalled();
  const calls = (AnalyticsService.logFunnelEvent as jest.Mock).mock.calls;
  const last = calls[calls.length - 1];
  expect(last[1]).toMatchObject({stage: 'solo_miraba', offer: 'ia_plus', door: 'chip', trigger: 'investing'});
});

it('says "Ya estás en la lista" when the server reports an earlier join', async () => {
  mockOffers = [];
  mockJoin.mockResolvedValue({data: {joinPaidOfferWaitlist: {success: true, waitlistedAt: '2026-10-01T12:00:00Z', alreadyListed: true}}});
  await mount();
  await act(async () => { press(tree, 'Sí, avísame').props.onPress(); });
  expect(texts(tree)).not.toContain('Anotado');
  expect(texts(tree)).toContain('Ya estás en la lista');
});

it('sends one answer on a double tap', async () => {
  mockOffers = [offer({onWaitlist: true, waitlistedAt: '2026-10-05T12:00:00Z'})];
  let resolve: (v: any) => void = () => {};
  mockAnswer.mockReturnValue(new Promise(r => { resolve = r; }));
  await mount();
  await act(async () => { const b = press(tree, 'Sí'); b.props.onPress(); b.props.onPress(); });
  expect(mockAnswer).toHaveBeenCalledTimes(1);
  await act(async () => resolve({data: {answerPaidOffer: {success: true}}}));
});

it('joins once on a double tap', async () => {
  mockJoin.mockResolvedValue({data: {joinPaidOfferWaitlist: {success: true, waitlistedAt: '2026-10-07T12:00:00Z'}}});
  await mount();
  await act(async () => { const b = press(tree, 'Sí, avísame'); b.props.onPress(); b.props.onPress(); });
  expect(mockJoin).toHaveBeenCalledTimes(1);
});
