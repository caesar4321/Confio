// "Dirección y teléfono" filled in right in the conversation.
import React from 'react';
import { Text as RNText, TextInput as RNTextInput } from 'react-native';
import renderer, { act } from 'react-test-renderer';

const mockSave = jest.fn();
const mockLog = jest.fn();
let mockAddress: any;
let mockPhone: any;
let mockRequirements: any;
let mockActivities: any[];
let mockEmail = 'ana@example.com';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => {
  const { Text, TextInput } = require('react-native');
  return { Text, TextInput };
});
jest.mock('../../apollo/queries', () => ({
  GET_MY_RAMP_ADDRESS: 'address', GET_RAMP_ADDRESS_REQUIREMENTS: 'requirements', GET_RAMP_PHONE_STATUS: 'phone',
  UPSERT_RAMP_USER_ADDRESS: 'save',
}));
jest.mock('@apollo/client', () => ({
  useMutation: () => [(...a: unknown[]) => mockSave(...a)],
  useQuery: (query: string) => ({
    loading: false,
    data: query === 'address' ? { myRampAddress: mockAddress, economicActivities: mockActivities, rampAddressRequirements: null }
      : query === 'phone' ? { myRampPhoneStatus: mockPhone }
      : { rampAddressRequirements: mockRequirements },
  }),
}));
jest.mock('../../config/localRails', () => ({ toIso2: (value: string) => value }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: { email: mockEmail } }) }));
jest.mock('../../services/analyticsService', () => ({ AnalyticsService: { logEvent: (...a: unknown[]) => mockLog(...a) } }));
jest.mock('../../utils/userCountry', () => ({ userCountryIso: () => 'BO' }));

import { AddressForm, addressProblem } from '../AddressForm';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType(RNText).map((n) => [n.props.children].flat(Infinity).join(''));
const input = (tree: renderer.ReactTestRenderer, label: string) =>
  tree.root.findAllByType(RNTextInput).find((n) => n.props.accessibilityLabel === label)!;
const type = async (tree: renderer.ReactTestRenderer, label: string, value: string) => {
  await act(async () => { input(tree, label).props.onChangeText(value); });
};
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === 'function')[0];
  if (!node) throw new Error(`no button ${label}; texts: ${texts(tree).join(' | ')}`);
  await act(async () => { await node.props.onPress(); });
};
const onSaved = jest.fn();
const onOpenScreen = jest.fn();
async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AddressForm label="Mi dirección" onSaved={onSaved} onOpenScreen={onOpenScreen} />); });
  await act(async () => { await Promise.resolve(); });
  return tree;
}
const NEEDS = { neighborhood: false, neighborhoodLabel: 'Colonia', activity: true, email: false, country: true };
const FULL = { street: 'Av. 6 de Agosto 123', neighborhood: '', city: 'La Paz', state: 'La Paz', zip: '0000',
  activity: 'COMERCIO', email: '' };

beforeEach(() => {
  jest.clearAllMocks();
  mockAddress = { addressCountry: 'BO' };
  mockPhone = { addressCountryIso: 'BO', contactPhone: '+59170000000' };
  mockRequirements = { requiresAddressNeighborhood: false };
  mockActivities = [{ label: 'Comercio al por menor', value: 'COMERCIO' }, { label: 'Servicios profesionales', value: 'SERVICIOS' }];
  mockEmail = 'ana@example.com';
  mockSave.mockResolvedValue({ data: { upsertRampUserAddress: { success: true } } });
});

it('says what is missing, one thing at a time, by the address screen\'s own rules', () => {
  expect(addressProblem({ ...FULL, street: ' ' }, NEEDS)).toBe('Escribe tu dirección.');
  expect(addressProblem({ ...FULL, city: '' }, NEEDS)).toBe('Escribe tu ciudad.');
  expect(addressProblem({ ...FULL, state: '' }, NEEDS)).toBe('Escribe tu provincia o estado.');
  expect(addressProblem({ ...FULL, zip: '' }, NEEDS)).toBe('Escribe tu código postal.');
  expect(addressProblem({ ...FULL, activity: '' }, NEEDS)).toBe('Elige tu actividad económica.');
  // Mexico: the colonia, by the name that rail gives it.
  expect(addressProblem(FULL, { ...NEEDS, neighborhood: true })).toBe('Escribe tu colonia.');
  // Colombia with a hidden Apple e-mail: a real one.
  expect(addressProblem({ ...FULL, email: 'x@privaterelay.appleid.com' }, { ...NEEDS, email: true })).toContain('correo real');
  expect(addressProblem({ ...FULL, email: 'ana@correo.com' }, { ...NEEDS, email: true })).toBe('');
  expect(addressProblem(FULL, { ...NEEDS, country: false })).toContain('No pude identificar tu país');
  expect(addressProblem(FULL, NEEDS)).toBe('');
});

it('Bolivia: the postal code comes filled in, the activity is picked from the provider\'s list, and it saves with the screen\'s mutation', async () => {
  const tree = await mount();
  expect(input(tree, 'Código postal').props.value).toBe('0000');
  await type(tree, 'Dirección', ' Av. 6 de Agosto 123 ');
  await type(tree, 'Ciudad', 'La Paz');
  await type(tree, 'Provincia o estado', 'La Paz');
  await press(tree, 'Guardar mi dirección');
  expect(texts(tree)).toContain('Elige tu actividad económica.');
  expect(mockSave).not.toHaveBeenCalled();
  await type(tree, 'Actividad económica', 'comer');
  await press(tree, 'Elegir Comercio al por menor');
  await press(tree, 'Guardar mi dirección');
  expect(mockSave.mock.calls[0][0].variables).toEqual({
    addressStreet: 'Av. 6 de Agosto 123', addressNeighborhood: undefined, addressCity: 'La Paz', addressState: 'La Paz',
    addressZipCode: '0000', economicActivity: 'COMERCIO', authEmail: undefined, addressCountry: 'BO',
  });
  // The phone is left as it is: nothing about it is sent.
  expect(Object.keys(mockSave.mock.calls[0][0].variables)).not.toContain('contactPhone');
  expect(texts(tree)).toEqual(['Listo: guardé tu dirección']);
  expect(onSaved).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it('what is saved comes filled in, and the server\'s refusal is said as it comes', async () => {
  mockAddress = { addressCountry: 'MX', addressStreet: 'Reforma 1', addressNeighborhood: 'Centro', addressCity: 'CDMX',
    addressState: 'CDMX', addressZipCode: '06000', economicActivity: 'SERVICIOS' };
  mockPhone = { addressCountryIso: 'MX', contactPhone: '+5215500000000' };
  mockRequirements = { requiresAddressNeighborhood: true, addressNeighborhoodLabel: 'Colonia' };
  const tree = await mount();
  expect(input(tree, 'Colonia').props.value).toBe('Centro');
  expect(input(tree, 'Dirección').props.value).toBe('Reforma 1');
  mockSave.mockResolvedValueOnce({ data: { upsertRampUserAddress: { success: false, error: 'Código postal no válido.' } } });
  await press(tree, 'Guardar mi dirección');
  expect(texts(tree)).toContain('Código postal no válido.');
  expect(onSaved).not.toHaveBeenCalled();
  expect(mockSave.mock.calls[0][0].variables).toMatchObject({ addressNeighborhood: 'Centro', addressCountry: 'MX' });
  await act(async () => tree.unmount());
});

it('a phone to add, or another country, is done on the screen', async () => {
  mockPhone = { addressCountryIso: 'BO', contactPhone: '' };
  let tree = await mount();
  expect(texts(tree).join(' ')).toContain('Falta también tu número de celular');
  await press(tree, 'Abrir Dirección y teléfono');
  expect(onOpenScreen).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
  mockPhone = { addressCountryIso: 'BO', contactPhone: '+59170000000' };
  tree = await mount();
  await press(tree, 'Cambiar país o teléfono');
  expect(onOpenScreen).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});
