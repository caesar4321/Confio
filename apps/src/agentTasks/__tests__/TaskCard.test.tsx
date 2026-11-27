// The general card: drawn from the server's blocks, answered with its binding, and the older drawing kept
// when the server sends none (or a version this build does not know).
import React from 'react';
import { Text as RNText } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const ID = '3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b';
let mockTask: any;
let mockCard: any;
const mockMutate = jest.fn();
const mockClient = {
  query: async ({ query }: any) => (String(query).includes('agentTaskCard')
    ? (mockCard instanceof Error ? Promise.reject(mockCard) : { data: { agentTaskCard: mockCard } })
    : { data: { agentTask: mockTask && { ...mockTask } } }),
  mutate: (options: any) => mockMutate(options),
};

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({
  Text: require('react-native').Text, TextInput: require('react-native').TextInput,
}));
jest.mock('react-native-qrcode-svg', () => 'QRCode');
jest.mock('react-native-view-shot', () => 'ViewShot');
jest.mock('react-native-share', () => ({ open: jest.fn() }));
jest.mock('../../utils/saveImageToGallery', () => ({ saveImageToGallery: jest.fn() }));
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray, ...v: unknown[]) => s.reduce((out, part, i) => out + part + (v[i] ?? ''), ''),
  useApolloClient: () => mockClient,
}));

import { PurchaseCard } from '../PurchaseCard';

const TASK = {
  id: ID, goal: 'un hostal en Salta', site: 'booking.com', status: 'needs_person', reason: 'act', kind: 'manage',
  message: 'En booking.com está lista tu reserva. ¿La confirmo?', waitUntil: '2099-01-01T00:00:00Z',
  paymentIntentId: null, order: null, options: [], request: 'Habitación doble, 3 al 6 feb', requestButton: 'Reservar',
};
const CARD = {
  version: 1, icon: 'bed', title: 'Habitación doble, 3 al 6 feb', subtitle: 'booking.com', image: '',
  lines: [{ label: 'Botón de booking.com', value: '«Reservar»' }], total: { label: 'Total', value: 'US$ 120', note: '' },
  notice: '', binding: 'b'.repeat(40), status: 'needs_person', reason: 'act',
  actions: [{ id: 'request_yes', label: 'Confirmar reserva', style: 'primary', screen: null },
    { id: 'request_no', label: 'No, déjalo así', style: 'link', screen: null }],
};
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const pressable = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => (n.props.accessibilityLabel === label || n.props.title === label)
    && typeof n.props.onPress === 'function')[0];

let trees: renderer.ReactTestRenderer[] = [];
async function mount(onOpen?: any) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<PurchaseCard taskId={ID} onOpen={onOpen} />); });
  trees.push(tree);
  return tree;
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  mockTask = { ...TASK };
  mockCard = { ...CARD };
  mockMutate.mockResolvedValue({ data: { answerAgentCard: { success: true, errors: [], task: { ...TASK } } } });
});
afterEach(() => {
  trees.forEach((t) => act(() => { t.unmount(); }));
  trees = [];
  jest.useRealTimers();
});

it('draws the server card in place of the older request card, and a tap sends its id and binding', async () => {
  const tree = await mount();
  const said = texts(tree);
  expect(said).toEqual(expect.arrayContaining(['Habitación doble, 3 al 6 feb', '«Reservar»', 'US$ 120']));
  expect(said).not.toContain('Sí, envíala');   // the older drawing is gone
  expect(tree.root.findAll((n) => (n.type as any) === 'Icon' && n.props.name === 'moon').length).toBe(1);
  await act(async () => { pressable(tree, 'Confirmar reserva').props.onPress(); });
  expect(mockMutate).toHaveBeenCalledTimes(1);
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, action: 'request_yes', binding: CARD.binding });
});

it('keeps the older drawing when the server has no card, fails, or sends a version it does not know', async () => {
  for (const card of [null, new Error('Cannot query field agentTaskCard'), { ...CARD, version: 2 }]) {
    mockCard = card;
    const tree = await mount();
    expect(texts(tree)).toContain('No, déjalo así');
    expect(pressable(tree, 'Sí, envíala')).toBeTruthy();
    act(() => { tree.unmount(); });
    trees = trees.filter((t) => t !== tree);
  }
});

it('a screen button opens the app screen and never calls the server; an unknown screen is left out', async () => {
  mockTask = { ...TASK, reason: 'subscribe', order: { item: 'x', total: '$1', image: '' } };
  mockCard = { ...CARD, reason: 'subscribe', actions: [
    { id: 'open_smart_account', label: 'Activar Cuenta inteligente', style: 'primary', screen: 'SmartAccountOffer' },
    { id: 'open_moon', label: 'Ir a la luna', style: 'primary', screen: 'MoonScreen' },
    { id: 'approve', label: 'Ya la activé: seguir', style: 'link', screen: null }] };
  const onOpen = jest.fn();
  const tree = await mount(onOpen);
  expect(texts(tree)).not.toContain('Ir a la luna');
  await act(async () => { pressable(tree, 'Activar Cuenta inteligente').props.onPress(); });
  expect(onOpen).toHaveBeenCalledWith('SmartAccountOffer', { door: 'chip', trigger: 'agent_purchase' });
  expect(mockMutate).not.toHaveBeenCalled();
});

it('a card built for another state than the task shown is not drawn', async () => {
  mockCard = { ...CARD, reason: 'approve' };
  const tree = await mount();
  expect(pressable(tree, 'Sí, envíala')).toBeTruthy();
  expect(texts(tree)).not.toContain('Confirmar reserva');
});

it('a card whose every button this build cannot do says to update', async () => {
  mockCard = { ...CARD, actions: [{ id: 'open', label: 'Abrir', style: 'primary', screen: 'Future' }] };
  const tree = await mount(jest.fn());
  expect(texts(tree)).toContain('Actualiza Confío para confirmar esto aquí.');
});
