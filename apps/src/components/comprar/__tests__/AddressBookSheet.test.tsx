import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('../../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ setOptions: jest.fn() }) }));
const mockBook = { current: [] as any[] };
const mockSave = jest.fn();
jest.mock('@apollo/client', () => ({
  gql: () => ({}),
  useQuery: () => ({ data: { myDeliveryAddresses: mockBook.current }, loading: false, refetch: jest.fn(() => Promise.resolve()) }),
  useMutation: () => [mockSave, { loading: false }],
}));

import { AddressBookSheet } from '../AddressBookSheet';

const RECARGA = { id: 'recarga', label: 'Mi dirección de Recarga', countryCode: 'BO', city: 'La Paz',
  address: 'Calle Jaén 711, Casco Viejo', phone: '+59171234567', note: '', isDefault: false, source: 'recarga', editable: false };
const FOREIGN = { ...RECARGA, id: '5', label: 'Casa Caracas', countryCode: 'VE', city: 'Caracas', source: 'saved', editable: true };

const render = (onSelect = jest.fn()) => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<AddressBookSheet visible countryCode="BO" city="La Paz" onClose={jest.fn()} onSelect={onSelect} />);
  });
  return { tree, onSelect };
};
const byId = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((n) => n.props.testID === id && (n.props.onPress || n.props.label))[0];

beforeEach(() => { mockBook.current = [RECARGA, FOREIGN]; mockSave.mockReset(); });

it('offers the Recarga address read-only, and dims addresses this store cannot deliver to', () => {
  const { tree, onSelect } = render();
  const recarga = byId(tree, 'address-recarga');
  expect(recarga.findAll((n) => n.props.accessibilityLabel === 'Editar').length).toBe(0);
  expect(recarga.findAll((n) => n.props.accessibilityLabel === 'Borrar').length).toBe(0);
  act(() => { recarga.props.onPress(); });
  expect(onSelect).toHaveBeenCalledWith(RECARGA);
  expect(byId(tree, 'address-5').props.disabled).toBe(true);
});

it('saves a new address and picks it', async () => {
  const created = { ...RECARGA, id: '9', label: 'Casa', source: 'saved', editable: true, address: 'Av. 6 de Agosto 1200, San Jorge' };
  mockSave.mockResolvedValue({ data: { saveDeliveryAddress: { success: true, address: created } } });
  const { tree, onSelect } = render();
  act(() => { byId(tree, 'address-new').props.onPress(); });
  const field = (ph: string) => tree.root.findAll((n) => n.props.placeholder === ph && typeof n.props.onChangeText === 'function')[0];
  act(() => { field('Dirección (calle, número, zona)').props.onChangeText('Av. 6 de Agosto 1200, San Jorge'); });
  act(() => { field('Teléfono para el repartidor').props.onChangeText('70011122'); });
  await act(async () => { byId(tree, 'address-save').props.onPress(); });
  expect(mockSave.mock.calls[0][0].variables).toEqual(expect.objectContaining({
    label: 'Casa', countryCode: 'BO', city: 'La Paz', address: 'Av. 6 de Agosto 1200, San Jorge', phone: '70011122',
  }));
  expect(onSelect).toHaveBeenCalledWith(created);
});
