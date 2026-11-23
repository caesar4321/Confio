// A top-up created right in the conversation, with the top-up screen's own checks.
import React from 'react';
import { Text as RNText, TextInput as RNTextInput } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
const mockCreate = jest.fn();
const mockBackup = jest.fn(async () => true);
const mockFace = jest.fn(async () => true);
const mockValidate = jest.fn(() => '');
let mockCountry: string | null = 'BO';
let mockAvailability: any;
let mockIdentity = true;
let mockNeedsDocument = false;
let mockAddress: any;
let mockMe: any;
let mockQuote: any;
let mockKept: any;
let mockReplaced = false;
const mockAttach = jest.fn(async () => ({}));
const mockRefetchIdentity = jest.fn(async () => ({ data: {} }));
const mockLogEvent = jest.fn();
let mockQuoteEnabled: boolean | undefined;

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => {
  const { Text, TextInput } = require('react-native');
  return { Text, TextInput };
});
jest.mock('../../apollo/mutations', () => ({ selectCreateRampOrderMutation: () => 'createOrder' }));
jest.mock('../../apollo/queries', () => ({
  GET_ME: 'me', GET_MY_IDENTITY_STATUS: 'identity', GET_MY_PERSONAL_KYC_STATUS: 'kyc', GET_MY_RAMP_ADDRESS: 'address',
  GET_RAMP_AVAILABILITY: 'availability', GET_RAMP_TEST_IDENTITY: 'testIdentity',
}));
jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => (strings[0].includes('attachAssistantTopUp') ? 'attach' : 'kept'),
  useMutation: (mutation: string) => [mutation === 'attach' ? (...a: unknown[]) => mockAttach(...(a as [])) : (...a: unknown[]) => mockCreate(...a)],
  useQuery: (query: string) => ({
    loading: false,
    refetch: (...a: unknown[]) => mockRefetchIdentity(...(a as [])),
    data: query === 'me' ? { me: mockMe }
      : query === 'availability' ? { rampAvailability: mockAvailability }
      : query === 'address' ? { myRampAddress: mockAddress }
      : query === 'kept' ? (mockKept ? { assistantTopUp: mockKept } : undefined)
      : {},
  }),
}));
jest.mock('../../hooks/useKoyweReplaced', () => ({ useKoyweReplaced: () => ({ topUp: mockReplaced, withdraw: false }) }));
jest.mock('../../services/analyticsService', () => ({ AnalyticsService: { logEvent: (...a: unknown[]) => mockLogEvent(...a) } }));
jest.mock('../../config/env', () => ({ isKoyweRoutingEnabledForCountry: (c: string | null) => !!c && c !== 'VE' }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: { email: 'ana@example.com' } }) }));
jest.mock('../../hooks/useBackupEnforcement', () => ({
  useBackupEnforcement: () => ({ checkBackupEnforcement: (...a: unknown[]) => mockBackup(...(a as [])), BackupEnforcementModal: () => null }),
}));
jest.mock('../../hooks/useRampCountry', () => ({ useRampCountry: () => ({ countryCode: mockCountry, loading: false }) }));
jest.mock('../../hooks/useRampQuoteFlow', () => ({
  useRampQuoteFlow: ({ amount, enabled }: { amount: string; enabled: boolean }) => {
    mockQuoteEnabled = enabled;
    return ({
    parsedAmount: Number(amount) || 0, amountReady: Number(amount) > 0, quote: Number(amount) > 0 ? mockQuote : null,
    quoteLoading: false, quoteError: null, amountError: '',
    });
  },
  validateRampContinue: (...a: unknown[]) => mockValidate(...(a as [])),
}));
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { isReady: () => true, navigate: (...a: unknown[]) => mockNavigate(...a) },
}));
jest.mock('../../services/faceStepUp', () => {
  class FaceCheckError extends Error {}
  return { FaceCheckError, isFaceStepUpRequired: () => false, withFaceStepUp: async (_p: string, run: () => Promise<unknown>) => run() };
});
jest.mock('../../services/authService', () => ({ ensureBscAddressRegistered: jest.fn(async () => {}) }));
jest.mock('../../utils/koyweTestIdentity', () => ({ hasKoyweTestIdentity: () => false }));
jest.mock('../../utils/numberLocale', () => ({
  sanitizeAmountInput: (value: string) => value, toAmountInput: (value: number) => String(value),
}));
jest.mock('../../utils/rampErrors', () => ({ getFriendlyRampError: (message?: string) => message || 'No se pudo crear la orden.' }));
jest.mock('../../utils/rampFlow', () => ({ requestRampCriticalAuth: (...a: unknown[]) => mockFace(...(a as [])) }));
jest.mock('../../utils/rampFormat', () => ({ USD_UNIT: 'USD', formatRampMoney: (value: string) => `US$${value}` }));
jest.mock('../../utils/rampIdentity', () => ({ hasRampIdentity: () => mockIdentity, needsCountryDocument: () => mockNeedsDocument }));
jest.mock('../TopUpOrderCard', () => ({ TopUpOrderCard: 'TopUpOrderCard' }));
jest.mock('../AddressForm', () => ({ AddressForm: 'AddressForm' }));

import { resolveTopUp, TopUpForm, topUpPrefill } from '../TopUpForm';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const input = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAllByType(RNTextInput).find((n) => n.props.accessibilityLabel === label)!;
const button = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = button(tree, label);
  if (!node) throw new Error(`no button ${label}; texts: ${texts(tree).join(' | ')}`);
  await act(async () => { await node.props.onPress(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
};
async function mount(props: Partial<React.ComponentProps<typeof TopUpForm>> = {}) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<TopUpForm messageId="77" label="Recargar 500 bolivianos" {...props} />); });
  await act(async () => { await Promise.resolve(); });
  return tree;
}
const CREATED = { data: { createRampOrder: {
  success: true, orderId: 'ord-1', paymentMethodDisplay: 'QR Simple', amountOut: '71.20', nextActionUrl: null,
  paymentDetails: '{"qr":"000201"}',
} } };

beforeEach(() => {
  jest.clearAllMocks();
  mockCountry = 'BO';
  mockIdentity = true;
  mockNeedsDocument = false;
  mockMe = { username: 'ana', email: 'ana@example.com' };
  mockAddress = { isComplete: true, authEmail: '' };
  mockQuote = { amountOut: '71.20' };
  mockAvailability = {
    countryCode: 'BO', fiatCurrency: 'BOB', onRampEnabled: true,
    onRampMethods: [{ code: 'QRI-BO', displayName: 'QR Simple', onRampMinAmount: '350', onRampMaxAmount: '56000' }],
  };
  mockBackup.mockResolvedValue(true);
  mockFace.mockResolvedValue(true);
  mockValidate.mockReturnValue('');
  mockCreate.mockResolvedValue(CREATED);
  mockKept = { status: 'none' };
  mockReplaced = false;
});

it('reads only the action the server writes', () => {
  expect(topUpPrefill('BOB=500')).toEqual({ currency: 'BOB', amount: '500' });
  expect(topUpPrefill('bob=500')).toBeNull();
  expect(resolveTopUp({ type: 'form', target: 'topup', label: 'Recargar' })).toEqual({ label: 'Recargar', prefill: null });
  expect(resolveTopUp({ type: 'form', target: 'topup:BOB=1500.50', label: 'x' })?.prefill).toEqual({ currency: 'BOB', amount: '1500.50' });
  for (const target of ['topup:500', 'topup:BOB=1,5', 'topup_other', 'profile_name', '']) {
    expect(resolveTopUp({ type: 'form', target, label: 'x' })).toBeNull();
  }
  expect(resolveTopUp({ type: 'do', target: 'topup', label: 'x' })).toBeNull();
});

it('fills in what the person wrote only in the currency they wrote it in', async () => {
  let tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  expect(input(tree, 'Cuánto pagas, en BOB').props.value).toBe('500');
  expect(texts(tree)).toEqual(expect.arrayContaining(['Pagas con QR Simple', 'US$71.20']));
  await act(async () => tree.unmount());
  // Their rail is in another currency: 500 pesos are not 500 bolivianos.
  tree = await mount({ prefill: { currency: 'ARS', amount: '500' } });
  expect(input(tree, 'Cuánto pagas, en BOB').props.value).toBe('');
  await act(async () => tree.unmount());
});

it('creates the order after the screen\'s own checks, and keeps its instructions here', async () => {
  const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  await press(tree, 'Crear recarga');
  expect(mockBackup).toHaveBeenCalledWith('bsc_deposit');
  expect(mockFace).toHaveBeenCalledWith({ amount: 500, assetUnit: 'USD', assetNote: 'ahorro', actionLabel: 'compra' });
  expect(mockCreate).toHaveBeenCalledWith({ variables: {
    direction: 'ON_RAMP', amount: '500', countryCode: 'BO', fiatCurrency: 'BOB', paymentMethodCode: 'QRI-BO',
    authEmail: undefined, destination: 'cusd_plus',
  } });
  const card = tree.root.findByType('TopUpOrderCard' as any);
  expect(card.props.order).toMatchObject({
    orderId: 'ord-1', countryCode: 'BO', paymentMethodCode: 'QRI-BO', paymentMethodDisplay: 'QR Simple', fiatCurrency: 'BOB',
    amountIn: '500', amountOut: '71.20', paymentDetails: '{"qr":"000201"}',
  });
  // The order is kept with the message, and counted like one made on the screen.
  expect(mockAttach).toHaveBeenCalledWith({ variables: {
    messageId: '77', orderId: 'ord-1', paymentMethodCode: 'QRI-BO', paymentMethodDisplay: 'QR Simple',
  } });
  expect(mockLogEvent.mock.calls.map(([name]) => name)).toEqual(['begin_checkout', 'add_payment_info']);
  await act(async () => { card.props.onOpen(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(mockNavigate).toHaveBeenCalledWith('RampInstructions', expect.objectContaining({ direction: 'ON_RAMP', orderId: 'ord-1' }));
  await act(async () => tree.unmount());
});

it('each missing step is said, with the one button that fixes it, and no order is created', async () => {
  const fresh = () => mount({ prefill: { currency: 'BOB', amount: '500' } });
  // The provider's limits and quote first.
  let tree = await fresh();
  mockValidate.mockReturnValueOnce('El mínimo es 350 BOB');
  await press(tree, 'Crear recarga');
  expect(texts(tree)).toContain('El mínimo es 350 BOB');
  expect(mockBackup).not.toHaveBeenCalled();
  // The wallet's backup.
  mockBackup.mockResolvedValueOnce(false);
  await press(tree, 'Crear recarga');
  expect(mockFace).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  // Identity (read again first: they may be just back from verifying).
  mockIdentity = false;
  tree = await fresh();
  await press(tree, 'Crear recarga');
  expect(mockRefetchIdentity).toHaveBeenCalled();
  expect(texts(tree)).toContain('Antes de recargar necesitamos validar tu identidad.');
  await press(tree, 'Verificar mi identidad');
  expect(mockNavigate).toHaveBeenLastCalledWith('Verification', undefined);
  await act(async () => tree.unmount());
  // Verified with another country's document: the screen has the choices for that.
  mockNeedsDocument = true;
  tree = await fresh();
  await press(tree, 'Crear recarga');
  await press(tree, 'Abrir Recargar');
  expect(mockNavigate).toHaveBeenLastCalledWith('TopUp', undefined);
  await act(async () => tree.unmount());
  // The address.
  mockIdentity = true;
  mockNeedsDocument = false;
  mockAddress = { isComplete: false };
  tree = await fresh();
  await press(tree, 'Crear recarga');
  // Filled in right here, under the amount; the screen only for another country or the phone.
  const address = tree.root.findByType('AddressForm' as any);
  expect(address.props.bare).toBe(true);
  await act(async () => { address.props.onOpenScreen(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(mockNavigate).toHaveBeenLastCalledWith('RampAddress', undefined);
  expect(mockFace).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
  // Confío Face declined.
  mockAddress = { isComplete: true };
  mockFace.mockResolvedValueOnce(false);
  tree = await fresh();
  await press(tree, 'Crear recarga');
  expect(mockCreate).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('an earlier unpaid top-up, or the provider\'s refusal, is said as it comes', async () => {
  const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  mockCreate.mockResolvedValueOnce({ data: { createRampOrder: {
    success: false, nextStep: 'resume_order', orderId: 'old-9', error: 'Ya tienes una recarga sin pagar.',
    countryCode: 'BO', fiatCurrency: 'BOB', paymentMethodCode: 'QRI-BO', paymentMethodDisplay: 'QR Simple',
  } } });
  await press(tree, 'Crear recarga');
  expect(texts(tree)).toContain('Ya tienes una recarga sin pagar.');
  await press(tree, 'Ver recarga pendiente');
  expect(mockNavigate).toHaveBeenLastCalledWith('RampInstructions', expect.objectContaining({ orderId: 'old-9' }));
  mockCreate.mockResolvedValueOnce({ data: { createRampOrder: { success: false, error: 'Monto fuera de rango.' } } });
  await press(tree, 'Crear recarga');
  expect(texts(tree)).toContain('Monto fuera de rango.');
  mockCreate.mockRejectedValueOnce(new Error('Network request failed'));
  await press(tree, 'Crear recarga');
  expect(texts(tree)).toContain('Network request failed');
  expect(tree.root.findAllByType('TopUpOrderCard' as any)).toHaveLength(0);
  await act(async () => tree.unmount());
});

it('Colombia: the bank\'s e-mail is asked for here when the account\'s is a hidden one', async () => {
  mockCountry = 'CO';
  mockMe = { username: 'ana', email: 'x1@privaterelay.appleid.com' };
  mockAvailability = { countryCode: 'CO', fiatCurrency: 'COP', onRampEnabled: true,
    onRampMethods: [{ code: 'PSE', displayName: 'PSE' }] };
  const tree = await mount({ prefill: { currency: 'COP', amount: '60000' } });
  await press(tree, 'Crear recarga');
  expect(texts(tree).join(' ')).toContain('Escribe un correo tuyo');
  expect(mockCreate).not.toHaveBeenCalled();
  await act(async () => { input(tree, 'Tu correo').props.onChangeText(' Ana@Correo.com '); });
  await press(tree, 'Crear recarga');
  expect(mockCreate.mock.calls[0][0].variables.authEmail).toBe('ana@correo.com');
  await act(async () => tree.unmount());
  // A deliverable one saved before is used without asking again.
  mockAddress = { isComplete: true, authEmail: 'Guardado@Correo.com' };
  mockCreate.mockClear();
  const again = await mount({ prefill: { currency: 'COP', amount: '60000' } });
  expect(again.root.findAllByType(RNTextInput).some((n) => n.props.accessibilityLabel === 'Tu correo')).toBe(false);
  await press(again, 'Crear recarga');
  expect(mockCreate.mock.calls[0][0].variables.authEmail).toBe('guardado@correo.com');
  await act(async () => again.unmount());
});

it('in the floating chat it hands over to the top-up screen with the amount written; where the rail is not this one, to Recargar', async () => {
  const onLeaveBox = jest.fn();
  jest.useFakeTimers();
  try {
    const tree = await mount({ prefill: { currency: 'BOB', amount: '500' }, onLeaveBox });
    const node = button(tree, 'Continuar en Recargar');
    await act(async () => { await node.props.onPress(); });
    await act(async () => { jest.advanceTimersByTime(300); });
    expect(onLeaveBox).toHaveBeenCalledTimes(1);
    expect(mockNavigate).toHaveBeenCalledWith('TopUp', { amount: '500', amountCurrency: 'BOB' });
    expect(mockCreate).not.toHaveBeenCalled();
    expect(mockFace).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  } finally {
    jest.useRealTimers();
  }
  mockAvailability = { countryCode: 'BO', fiatCurrency: 'BOB', onRampEnabled: false, onRampMethods: [] };
  const paused = await mount();
  expect(texts(paused).join(' ')).toContain('Desde aquí no puedo crear esta recarga');
  await press(paused, 'Abrir Recargar');
  expect(mockNavigate).toHaveBeenLastCalledWith('Receive', undefined);
  await act(async () => paused.unmount());
});

it('after a restart the conversation shows the order this form created, never the form again', async () => {
  mockKept = { status: 'order', orderId: 'ord-1', countryCode: 'BO', fiatCurrency: 'BOB', fiatAmount: '500',
    paymentMethodCode: 'QRI-BO', paymentMethodDisplay: 'QR Simple' };
  const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  expect(tree.root.findByType('TopUpOrderCard' as any).props.order).toMatchObject({
    orderId: 'ord-1', paymentMethodCode: 'QRI-BO', amountIn: '500', fiatCurrency: 'BOB',
  });
  expect(button(tree, 'Crear recarga')).toBeUndefined();
  await act(async () => tree.unmount());
});

it('an old form, one that is not theirs, or one whose state is unknown creates nothing and asks the provider nothing', async () => {
  for (const [kept, said] of [
    [{ status: 'expired' }, 'Este formulario venció. Pídeme la recarga de nuevo.'],
    [{ status: 'gone' }, 'Este formulario ya no está disponible.'],
    [undefined, 'Preparando…'],
  ] as const) {
    mockKept = kept;
    mockQuoteEnabled = undefined;
    const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
    expect(texts(tree)).toContain(said);
    expect(button(tree, 'Crear recarga')).toBeUndefined();
    expect(mockQuoteEnabled).toBe(false);
    await act(async () => tree.unmount());
  }
});

it('where QR Bolivia took Koywe\'s place, this form is not their top-up any more', async () => {
  mockReplaced = true;
  const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  expect(texts(tree).join(' ')).toContain('Desde aquí no puedo crear esta recarga');
  expect(button(tree, 'Crear recarga')).toBeUndefined();
  await act(async () => tree.unmount());
});

it('a currency that turns out to be another takes the filled amount back, and the title stops naming it', async () => {
  const tree = await mount({ prefill: { currency: 'BOB', amount: '500' } });
  expect(input(tree, 'Cuánto pagas, en BOB').props.value).toBe('500');
  // Their rail country arrives a moment later: the form is in soles.
  mockAvailability = { countryCode: 'PE', fiatCurrency: 'PEN', onRampEnabled: true,
    onRampMethods: [{ code: 'QRI-PE', displayName: 'QR' }] };
  await act(async () => { tree.update(<TopUpForm messageId="77" label="Recargar 500 bolivianos" prefill={{ currency: 'BOB', amount: '500' }} />); });
  expect(input(tree, 'Cuánto pagas, en PEN').props.value).toBe('');
  expect(texts(tree)).toContain('Recargar');
  expect(texts(tree)).not.toContain('Recargar 500 bolivianos');
  await act(async () => tree.unmount());
});
