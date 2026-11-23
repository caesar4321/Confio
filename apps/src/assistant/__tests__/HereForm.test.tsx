// Details typed right in the conversation: a short form under the answer.
import React from 'react';
import { Text as RNText, TextInput as RNTextInput } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockMutate = jest.fn();
const mockQuery = jest.fn(async () => ({ data: { vePagomovilBanks: [
  { code: '0102', name: 'Banco de Venezuela' }, { code: '0134', name: 'Banesco' }, { code: '0105', name: 'Mercantil' },
] } }));
const mockRefreshProfile = jest.fn(async () => {});
const mockPrepare = jest.fn();
const onPrepared = jest.fn();

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => {
  const { Text, TextInput } = require('react-native');
  return { Text, TextInput };
});
// Like Apollo's, the same client on every render.
const mockClient = { mutate: (...a: unknown[]) => mockMutate(...a), query: (...a: unknown[]) => mockQuery(...(a as [])) };
jest.mock('@apollo/client', () => ({ useApolloClient: () => mockClient }));
jest.mock('../../apollo/queries', () => ({ UPDATE_USER_PROFILE: 'updateProfile' }));
jest.mock('../../apollo/mutations', () => ({ UPDATE_INVESTOR_BIO: 'updateBio' }));
jest.mock('../../services/agenda', () => ({ SAVE_VE_AGENDA_ENTRY: 'saveAgenda' }));
jest.mock('../../services/vePagoMovilTopUp', () => ({ VE_BANKS: 'banks' }));
jest.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ userProfile: { firstName: 'Ana', lastName: 'Perez' }, refreshProfile: mockRefreshProfile }),
}));
jest.mock('../../services/paymentIntent', () => {
  class PaymentIntentError extends Error {
    code: string;
    constructor(message: string, code = '') { super(message); this.code = code; }
  }
  return { PaymentIntentError, prepareRequestInChat: (...a: unknown[]) => mockPrepare(...a) };
});

import { HERE_FORMS, HereForm, formProblem, resolveForm } from '../HereForm';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const field = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAllByType(RNTextInput).find((n) => n.props.accessibilityLabel === label)!;
const type = async (tree: renderer.ReactTestRenderer, label: string, value: string) => {
  await act(async () => { field(tree, label).props.onChangeText(value); });
};
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
  if (!node) throw new Error(`no button ${label}`);
  await act(async () => { await node.props.onPress(); });
};
async function mount(formKey: string, label = 'Formulario') {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<HereForm formKey={formKey} label={label} onPrepared={onPrepared} />); });
  return tree;
}
const fillContact = async (tree: renderer.ReactTestRenderer) => {
  await type(tree, 'Nombre para reconocerlo', 'Mamá');
  await type(tree, 'Titular de la cuenta', 'Rosa Perez');
  await type(tree, 'Teléfono', '04141234567');
  await type(tree, 'Cédula', 'V12345678');
  await type(tree, 'Banco', 'banes');
  await press(tree, 'Elegir Banesco');
};

beforeEach(() => jest.clearAllMocks());

it('only the forms this build knows', () => {
  expect(resolveForm({ type: 'form', target: 'profile_name', label: 'Cambiar mi nombre' }))
    .toEqual({ key: 'profile_name', label: 'Cambiar mi nombre' });
  for (const bad of ['delete_account', 'constructor', '']) {
    expect(resolveForm({ type: 'form', target: bad, label: 'x' })).toBeNull();
  }
  expect(resolveForm({ type: 'do', target: 'profile_name', label: 'x' })).toBeNull();
  expect(Object.keys(HERE_FORMS).sort()).toEqual(['agenda_pagomovil', 'investor_bio', 'pagomovil_payment', 'profile_name']);
});

it('says what is still missing, one thing at a time', () => {
  // Only the first name is required, as on the profile screen.
  expect(formProblem('profile_name', { lastName: 'Perez' }, null)).toBe('Escribe tu nombre.');
  expect(formProblem('profile_name', { firstName: 'Ana' }, null)).toBe('');
  const base = { label: 'Mamá', holderName: 'Rosa Perez', phone: '0414 123 4567', cedula: 'V-12.345.678' };
  expect(formProblem('agenda_pagomovil', { ...base, holderName: '' }, null)).toBe('Escribe el nombre del titular de la cuenta.');
  expect(formProblem('agenda_pagomovil', {}, null)).toBe('Ponle un nombre para reconocerlo.');
  expect(formProblem('agenda_pagomovil', { ...base, phone: '0414' }, null)).toBe('Escribe el teléfono completo.');
  expect(formProblem('agenda_pagomovil', base, null)).toBe('Elige el banco.');
  expect(formProblem('agenda_pagomovil', base, { code: '0134', name: 'Banesco' })).toBe('');
  expect(formProblem('pagomovil_payment', base, { code: '0134', name: 'Banesco' })).toBe('Escribe cuántos dólares quieres enviar.');
  expect(formProblem('pagomovil_payment', { ...base, amountUsd: '20,5' }, { code: '0134', name: 'Banesco' })).toBe('');
  // "1,500" is a thousand five hundred to some and one and a half to others: not guessed.
  for (const unclear of ['1,500', '1.500', '1.000,50', 'veinte', '0']) {
    expect(formProblem('pagomovil_payment', { ...base, amountUsd: unclear }, { code: '0134', name: 'Banesco' }))
      .toMatch(/monto/);
  }
});

it('the name: starts from what it is, saves through the app\'s own mutation, and the app hears of it', async () => {
  mockMutate.mockResolvedValue({ data: { updateUserProfile: { success: true } } });
  const tree = await mount('profile_name', 'Cambiar mi nombre');
  expect(field(tree, 'Nombre').props.value).toBe('Ana');
  await type(tree, 'Apellido', ' Pérez ');
  await press(tree, 'Guardar');
  expect(mockMutate).toHaveBeenCalledWith({ mutation: 'updateProfile', variables: { firstName: 'Ana', lastName: 'Pérez' } });
  expect(mockRefreshProfile).toHaveBeenCalledWith('personal');
  expect(texts(tree)).toEqual(['Listo: guardé tu nombre']);
  await act(async () => tree.unmount());
});

it('a contact goes to Agenda with what the person typed, and nothing is sent until it is complete', async () => {
  mockMutate.mockResolvedValue({ data: { saveVePagomovilAgendaEntry: { success: true, entry: {} } } });
  const tree = await mount('agenda_pagomovil', 'Guardar un contacto de Pago Móvil');
  await press(tree, 'Guardar en mi Agenda');
  expect(texts(tree)).toContain('Ponle un nombre para reconocerlo.');
  expect(mockMutate).not.toHaveBeenCalled();
  await fillContact(tree);
  await press(tree, 'Guardar en mi Agenda');
  expect(mockMutate).toHaveBeenCalledWith({
    mutation: 'saveAgenda', fetchPolicy: 'no-cache',
    variables: { id: null, label: 'Mamá', relationship: null, holderName: 'Rosa Perez', cedula: 'V12345678',
      phone: '04141234567', bankCode: '0134' },
  });
  expect(texts(tree)).toEqual(['Listo: guardé a Mamá en tu Agenda']);
  expect(mockPrepare).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('a Pago Móvil payment: the contact is saved first, then the payment is prepared for review', async () => {
  mockMutate.mockResolvedValue({ data: { saveVePagomovilAgendaEntry: { success: true, entry: {} } } });
  mockPrepare.mockResolvedValue({ id: 'intent-1' });
  const tree = await mount('pagomovil_payment', 'Enviar por Pago Móvil');
  await fillContact(tree);
  await type(tree, 'Cuántos dólares envías', '20');
  await press(tree, 'Preparar el pago');
  expect(mockMutate).toHaveBeenCalledTimes(1);
  expect(mockPrepare).toHaveBeenCalledWith({
    methodId: 've_pagomovil_send', phone: '04141234567', cedula: 'V12345678', bankCode: '0134',
    holderName: 'Rosa Perez', amountUsd: '20',
  });
  expect(onPrepared).toHaveBeenCalledTimes(1);
  expect(texts(tree)).toEqual(['Listo: revisa el pago en la tarjeta de abajo']);
  await act(async () => tree.unmount());
});

it('a refusal is said on the form, which stays to be corrected', async () => {
  mockMutate.mockResolvedValue({ data: { saveVePagomovilAgendaEntry: { success: false, errors: ['La cédula no es válida.'] } } });
  const tree = await mount('pagomovil_payment');
  await fillContact(tree);
  await type(tree, 'Cuántos dólares envías', '20');
  await press(tree, 'Preparar el pago');
  expect(texts(tree)).toContain('La cédula no es válida.');
  expect(mockPrepare).not.toHaveBeenCalled();
  expect(onPrepared).not.toHaveBeenCalled();
  const { PaymentIntentError } = require('../../services/paymentIntent');
  mockMutate.mockResolvedValue({ data: { saveVePagomovilAgendaEntry: { success: true, entry: {} } } });
  mockPrepare.mockRejectedValue(new PaymentIntentError('Pago Móvil no está disponible ahora.', 'rail'));
  await press(tree, 'Preparar el pago');
  expect(texts(tree)).toContain('Pago Móvil no está disponible ahora.');
  await act(async () => tree.unmount());
});

describe('the investor description', () => {
  it('is checked here, saved by the app\'s own mutation, and the rules are a consent given elsewhere', async () => {
    expect(formProblem('investor_bio', { bio: ' ' }, null)).toBe('Escribe tu descripción.');
    expect(formProblem('investor_bio', { bio: 'x'.repeat(141) }, null)).toContain('140');
    expect(formProblem('investor_bio', { bio: 'mira www.ejemplo.com' }, null)).toContain('enlaces');
    expect(formProblem('investor_bio', { bio: 'Ahorro en dólares' }, null)).toBe('');

    const tree = await mount('investor_bio', 'Escribir mi descripción');
    await type(tree, 'Tu descripción', '  Ahorro en dólares  ');
    expect(texts(tree)).toContain('21/140');
    mockMutate.mockResolvedValueOnce({ data: { updateInvestorBio: { success: false, rulesRequired: true } } });
    await press(tree, 'Guardar');
    expect(mockMutate).toHaveBeenLastCalledWith({ mutation: 'updateBio', variables: { bio: 'Ahorro en dólares' } });
    expect(texts(tree).join(' ')).toContain('normas de la Comunidad');
    // The reviewer's own reason is shown as it comes.
    mockMutate.mockResolvedValueOnce({ data: { updateInvestorBio: { success: false, rulesRequired: false, error: 'No pasó la revisión.' } } });
    await press(tree, 'Guardar');
    expect(texts(tree)).toContain('No pasó la revisión.');
    mockMutate.mockResolvedValueOnce({ data: { updateInvestorBio: { success: true, bio: 'Ahorro en dólares' } } });
    await press(tree, 'Guardar');
    expect(texts(tree)).toContain('Listo: guardé tu descripción');
    await act(async () => tree.unmount());
  });
});
