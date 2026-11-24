// The assistant's purchase in the chat: products to pick, the store's sign-in, the order to approve.
import React from 'react';
import { Alert, Text as RNText, TextInput as RNTextInput } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const ID = '3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b';
let mockTask: any;
const mockQuery = jest.fn(async () => ({ data: { agentTask: mockTask && { ...mockTask } } }));
const mockMutate = jest.fn();
const mockClient = { query: () => mockQuery(), mutate: (options: any) => mockMutate(options) };

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({
  Text: require('react-native').Text, TextInput: require('react-native').TextInput,
}));
jest.mock('react-native-qrcode-svg', () => 'QRCode');
const mockCapture = jest.fn(async () => 'file:///tmp/qr.jpg');
jest.mock('react-native-view-shot', () => {
  const ReactLib = require('react');
  return ReactLib.forwardRef((props: any, ref: any) => {
    ReactLib.useImperativeHandle(ref, () => ({ capture: mockCapture }));
    return props.children;
  });
});
const mockShare = jest.fn(async (_options: any) => ({}));
jest.mock('react-native-share', () => ({ open: (o: any) => mockShare(o) }));
const mockSave = jest.fn(async (_uri: string) => undefined);
jest.mock('../../utils/saveImageToGallery', () => ({ saveImageToGallery: (uri: string) => mockSave(uri) }));
jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray, ...v: unknown[]) => s.reduce((out, part, i) => out + part + (v[i] ?? ''), ''),
  useApolloClient: () => mockClient,
}));

import { PurchaseCards } from '../PurchaseCards';
import { forgetCards } from '../helpers';

const task = (over: any = {}) => ({
  id: ID, goal: 'un chocolate', site: 'amazon.com.mx', status: 'needs_person', reason: 'choose',
  message: 'Encontré estas opciones en amazon.com.mx. Elige una y yo sigo.', waitUntil: '2099-01-01T00:00:00Z',
  paymentIntentId: null, order: null,
  options: [{ title: 'Chocolate Abuelita 6 tabletas', price: '$89.00', image: 'https://img.example/a.jpg' },
    { title: 'Chocolate Ibarra 540 g', price: '$112.50', image: 'http://plain.example/b.jpg' }],
  ...over,
});
const ACTION = [{ type: 'task', target: ID }];
const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const labelled = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
const answered = (name: string, over: any = {}) => ({ data: { [name]: { success: true, errors: [], ...over } } });

let trees: renderer.ReactTestRenderer[] = [];
async function mount(element = <PurchaseCards actions={ACTION} messageId="m1" createdAt="2026-11-23T20:00:00Z" />) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(element); });
  trees.push(tree);
  return tree;
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  forgetCards();
  mockTask = task();
  mockMutate.mockResolvedValue(answered('chooseAgentOption'));
});
afterEach(() => {
  trees.forEach((t) => act(() => { t.unmount(); }));
  trees = [];
  jest.useRealTimers();
});

it('shows the products with their photos and prices, and a tap picks one', async () => {
  const tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining(['Chocolate Abuelita 6 tabletas', '$89.00', '$112.50']));
  const photos = tree.root.findAll((n) => (n.type as any) === 'Image' && n.props.source);
  // Only https pictures are loaded.
  expect(photos.map((p) => p.props.source.uri)).toEqual(['https://img.example/a.jpg']);
  await act(async () => { labelled(tree, 'Elegir Chocolate Ibarra 540 g, $112.50').props.onPress(); });
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, index: 1 });
});

it('the sign-in is typed in the card, sent once, and the password is not kept', async () => {
  mockTask = task({ reason: 'login', options: [], message: 'Para comprar en amazon.com.mx necesito entrar…' });
  mockMutate.mockResolvedValue(answered('signInAgentStore'));
  const tree = await mount();
  const [user, password] = tree.root.findAllByType(RNTextInput);
  expect(password.props.secureTextEntry).toBe(true);
  await act(async () => { user.props.onChangeText(' ana@example.com '); password.props.onChangeText('hunter2!'); });
  await act(async () => { labelled(tree, 'Entrar').props.onPress(); });
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, identifier: 'ana@example.com', password: 'hunter2!' });
  expect(mockMutate.mock.calls[0][0].fetchPolicy).toBe('no-cache');
});

it('the sign-in says what is true about it: kept encrypted, theirs to delete, never "not stored"', async () => {
  mockTask = task({ reason: 'login', options: [], message: 'Para comprar en amazon.com.mx necesito entrar…' });
  const tree = await mount();
  const said = texts(tree).join(' ').replace(/\s+/g, ' ');
  expect(said).toContain('Se guarda cifrada y solo se usa para iniciar sesión en amazon.com.mx');
  expect(said).toContain('Puedes borrarla cuando quieras');
  expect(said).not.toMatch(/no (la |se )?guard|nunca la vemos/i);
  expect(tree.root.findAll((n) => (n.type as any) === 'Icon' && n.props.name === 'lock').length).toBeGreaterThan(0);
});

it('the order is approved with one tap, showing the item and the total', async () => {
  mockTask = task({ reason: 'approve', options: [], message: 'Listo para pedir…',
    order: { item: 'Chocolate Ibarra 540 g', total: '$112.50', image: 'https://img.example/b.jpg' } });
  mockMutate.mockResolvedValue(answered('approveAgentOrder'));
  const tree = await mount();
  expect(texts(tree)).toEqual(expect.arrayContaining(['Chocolate Ibarra 540 g', '$112.50']));
  await act(async () => { labelled(tree, 'Confirmar pedido').props.onPress(); });
  expect(mockMutate).toHaveBeenCalledTimes(1);
  // Bound to the total on the card they saw.
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, total: '$112.50' });
});

it('while it works the journey says where the purchase is, with small talk that never says bought', async () => {
  mockTask = task({ status: 'working', reason: '', options: [], stage: 'cart', message: 'Preparando tu carrito en amazon.com.mx…' });
  const tree = await mount();
  const journey = tree.root.findAll((n) => n.props.accessibilityRole === 'progressbar')[0];
  expect(journey.props.accessibilityLabel).toBe('Paso 2 de 4: Carrito');
  const shown = texts(tree);
  expect(shown).toEqual(expect.arrayContaining(['Buscar', 'Carrito', 'Pedido', 'Pago', 'Poniéndolo en el carrito…']));
  await act(async () => { jest.advanceTimersByTime(3700); });
  expect(texts(tree)).toContain('Revisando que solo vaya lo tuyo…');
  expect(texts(tree).join(' ')).not.toMatch(/compr[eé]|pagu[eé]|pedido hecho/i);
});

it('when it is their turn the journey stands still: no small talk', async () => {
  mockTask = task({ stage: 'search' });   // choosing a product
  const tree = await mount();
  expect(tree.root.findAll((n) => n.props.accessibilityRole === 'progressbar').length).toBeGreaterThan(0);
  expect(texts(tree)).not.toContain('Recorriendo los pasillos de amazon.com.mx…');
});

it('an order that becomes done while the card watches gets its moment, once', async () => {
  const { Vibration } = require('react-native');
  const buzz = jest.spyOn(Vibration, 'vibrate').mockImplementation(() => undefined);
  mockTask = task({ status: 'working', reason: '', options: [], stage: 'pay' });
  const tree = await mount();
  expect(tree.root.findAll((n) => n.props.testID === 'purchase-confetti')).toHaveLength(0);
  mockTask = task({ status: 'payment_ready', reason: '', options: [], stage: 'done', paymentIntentId: 'p-1',
    message: 'Preparé el pago.' });
  await act(async () => { jest.advanceTimersByTime(2600); });
  expect(texts(tree)).toContain('¡Pedido hecho!');
  expect(tree.root.findAll((n) => n.props.testID === 'purchase-confetti').length).toBeGreaterThan(0);
  expect(buzz).toHaveBeenCalledTimes(1);
  const journey = tree.root.findAll((n) => n.props.accessibilityRole === 'progressbar')[0];
  expect(journey.props.accessibilityLabel).toBe('Pedido hecho');
  buzz.mockRestore();
});

it('an order already done when the card opens is shown quietly', async () => {
  const { Vibration } = require('react-native');
  const buzz = jest.spyOn(Vibration, 'vibrate').mockImplementation(() => undefined);
  mockTask = task({ status: 'payment_ready', reason: '', options: [], stage: 'done', paymentIntentId: 'p-1' });
  const tree = await mount();
  expect(texts(tree)).toContain('¡Pedido hecho!');
  expect(tree.root.findAll((n) => n.props.testID === 'purchase-confetti')).toHaveLength(0);
  expect(buzz).not.toHaveBeenCalled();
  buzz.mockRestore();
});

it('a step the agent could not judge is one tap: yes or no', async () => {
  mockTask = task({ reason: 'step', options: [], message: 'amazon.com.mx pide «Guardar para más tarde» para seguir. ¿lo hago?' });
  mockMutate.mockResolvedValue(answered('answerAgentStep', { task: { ...mockTask, status: 'working', reason: '' } }));
  const tree = await mount();
  const yes = tree.root.findAll((n) => n.props.title === 'Sí, hazlo' && typeof n.props.onPress === 'function')[0];
  await act(async () => { yes.props.onPress(); });
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, yes: true });
});

it('the order card says where it is delivered', async () => {
  mockTask = task({ reason: 'approve', options: [],
    order: { item: 'Chocolate Ibarra', total: '$189.00', image: '', address: 'ana perez, calle 1 #23, cdmx' } });
  const tree = await mount();
  expect(texts(tree)).toContain('Envío a: ana perez, calle 1 #23, cdmx');
});

it('a code the store sent is typed in the card', async () => {
  mockTask = task({ reason: 'otp', options: [], message: 'amazon.com.mx te envió un código…' });
  mockMutate.mockResolvedValue(answered('giveAgentCode'));
  const tree = await mount();
  await act(async () => { tree.root.findByType(RNTextInput).props.onChangeText('482913'); });
  await act(async () => { labelled(tree, 'Enviar código').props.onPress(); });
  expect(mockMutate.mock.calls[0][0].variables).toEqual({ id: ID, code: '482913' });
});

it('while the agent works there is nothing to tap but cancelling, which asks first', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
  mockTask = task({ status: 'working', reason: '', options: [], message: 'Buscando en amazon.com.mx…' });
  const tree = await mount();
  expect(labelled(tree, 'Confirmar pedido')).toBeUndefined();
  await act(async () => {
    tree.root.findAll((n) => n.props.accessibilityRole === 'button' && typeof n.props.onPress === 'function')[0]
      .props.onPress();
  });
  expect(mockMutate).not.toHaveBeenCalled();
  expect(alert).toHaveBeenCalled();
});

it('one purchase, several notes: the card is drawn once, under the newest', async () => {
  const older = await mount(<PurchaseCards actions={ACTION} messageId="m1" createdAt="2026-11-23T20:00:00Z" />);
  const newer = await mount(<PurchaseCards actions={ACTION} messageId="m2" createdAt="2026-11-23T20:01:00Z" />);
  expect(texts(older)).toEqual([]);
  expect(texts(newer)).toContain('amazon.com.mx');
});

it("with QR Bolivia off the store's QR is in the card, to save and pay from the bank", async () => {
  mockTask = task({ site: 'tienda.com.bo', status: 'payment_ready', reason: 'manual', waitUntil: null,
    message: 'Tu pedido en tienda.com.bo está hecho. Págalo tú con el QR de abajo desde la app de tu banco.',
    payQr: '0002010102BOQR', order: { item: 'Chocolate', total: 'Bs 150', image: '' } });
  const tree = await mount();
  const qr = tree.root.findAll((n) => (n.type as any) === 'QRCode')[0];
  expect(qr.props.value).toBe('0002010102BOQR');
  expect(texts(tree)).toContain('Bs 150');
  const save = tree.root.findAll((n) => n.props.title === 'Guardar QR' && typeof n.props.onPress === 'function')[0];
  await act(async () => { await save.props.onPress(); });
  expect(mockSave).toHaveBeenCalledWith('file:///tmp/qr.jpg');
  expect(texts(tree).join(' ')).toContain('Súbelo en la app de tu banco');
  // Nothing to cancel: the order is the store's now.
  expect(texts(tree)).not.toContain('Cancelar la compra');
});

it('without a local account the CLABE, amount and reference are in the card, and the account is offered', async () => {
  mockTask = task({ site: 'amazon.com.mx', status: 'payment_ready', reason: 'manual', waitUntil: null,
    message: 'Tu pedido en amazon.com.mx está hecho.', payQr: null, openAccountMethod: 'mx_clabe',
    payDetails: [{ label: 'CLABE', value: '012180001234567897' }, { label: 'Monto', value: '$1,249.00' },
      { label: 'Referencia', value: '4021775' }],
    order: { item: 'Chocolate', total: '$1,249.00', image: '' } });
  const onOpen = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<PurchaseCards actions={ACTION} messageId="m1" createdAt="2026-11-23T20:00:00Z" onOpen={onOpen} />);
  });
  trees.push(tree);
  const shown = texts(tree);
  expect(shown).toEqual(expect.arrayContaining(['012180001234567897', '$1,249.00', '4021775']));
  const clipboard = require('@react-native-clipboard/clipboard');
  await act(async () => { labelled(tree, 'Copiar CLABE').props.onPress(); });
  expect((clipboard.default ?? clipboard).setString).toHaveBeenCalledWith('012180001234567897');
  const open = tree.root.findAll((n) => n.props.title === 'Abrir mi cuenta local' && typeof n.props.onPress === 'function')[0];
  act(() => { open.props.onPress(); });
  expect(onOpen).toHaveBeenCalledWith('LocalAccountApplication', { methodId: 'mx_clabe' });
});

it('no QR is drawn for a card Confío pays', async () => {
  mockTask = task({ status: 'payment_ready', reason: '', paymentIntentId: 'p-1', payQr: null });
  const tree = await mount();
  expect(tree.root.findAll((n) => (n.type as any) === 'QRCode')).toHaveLength(0);
});

it('a refusal is said on the card and the card stays', async () => {
  mockMutate.mockResolvedValue({ data: { chooseAgentOption: { success: false, errors: ['Esto ya no está esperando tu respuesta.'] } } });
  const tree = await mount();
  await act(async () => { labelled(tree, 'Elegir Chocolate Abuelita 6 tabletas, $89.00').props.onPress(); });
  expect(texts(tree)).toContain('Esto ya no está esperando tu respuesta.');
});
