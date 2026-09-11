import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Text, TextInput, TouchableOpacity } from 'react-native';

jest.mock('react-native-safe-area-context', () => ({ SafeAreaView: 'SafeAreaView' }));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-svg', () => ({
  __esModule: true, default: 'Svg', Defs: 'Defs', LinearGradient: 'LinearGradient',
  Stop: 'Stop', Rect: 'Rect', Circle: 'Circle',
}));
jest.mock('../../apollo/queries', () => ({
  GET_COUNTRIES: 'countries', GET_KOYWE_BANK_INFO: 'banks', GET_RAMP_PAYMENT_METHODS: 'methods',
  GET_USER_BANK_ACCOUNTS: 'accounts', CREATE_BANK_INFO: 'create', UPDATE_BANK_INFO: 'update',
}));
const mockCreate = jest.fn();
const mockUpdate = jest.fn();
const mockClient = { refetchQueries: jest.fn(), clearStore: jest.fn(), reFetchObservableQueries: jest.fn() };
const mockCountry = { id: 'co', code: 'CO', name: 'Colombia', flagEmoji: 'CO', requiresIdentification: false, identificationName: '' };
const mockMethod = {
  id: 'bancolombia', name: 'BANCOLOMBIA', code: 'BANCOLOMBIA', displayName: 'Bancolombia', providerType: 'bank', icon: 'bank',
  requiresAccountNumber: true, requiresPhone: false, requiresEmail: false, supportsOffRamp: true,
  country: mockCountry,
  fieldSchema: {
    defaultProviderMetadata: { bankCode: 'co_bancolombia' },
    accountField: { label: 'Número de cuenta Bancolombia', placeholder: 'Cuenta bancaria', show: true, required: true, keyboardType: 'numeric' as const, maxLength: 11 },
    showAccountTypeField: true, accountTypeRequired: true,
  },
};
const mockMethods = [mockMethod, { ...mockMethod, id: 'nequi', code: 'NEQUI', displayName: 'Nequi', providerType: 'fintech', fieldSchema: { defaultProviderMetadata: { bankCode: 'co_nequi' } } }];
jest.mock('@apollo/client', () => ({
  useQuery: (query: string) => ({ loading: false, data: query === 'countries' ? { countries: [mockCountry, { ...mockCountry, id: 'pe', code: 'PE', name: 'Perú' }] } : query === 'methods' ? { rampPaymentMethods: mockMethods } : { koyweBankInfo: [] } }),
  useMutation: (query: string) => [query === 'create' ? mockCreate : mockUpdate],
  useApolloClient: () => mockClient,
}));
import { AddPayoutMethodModal } from '../AddPayoutMethodModal';

const trees: renderer.ReactTestRenderer[] = [];
const render = (editing = false, metadata: Record<string, string> = { bankCode: 'co_bancolombia', rail: 'BREB' }, defaults: Record<string, string> = mockMethod.fieldSchema.defaultProviderMetadata) => {
  const editingMethod = { ...mockMethod, fieldSchema: { ...mockMethod.fieldSchema, defaultProviderMetadata: defaults } };
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<AddPayoutMethodModal isVisible onClose={jest.fn()} onSuccess={jest.fn()} accountId="1"
      initialCountryCode="CO" initialPaymentMethodId="bancolombia"
      editingPayoutMethod={editing ? {
        id: 'saved', account: { id: '1', accountId: '1', displayName: 'Personal', accountType: 'personal' },
        paymentMethod: editingMethod, rampPaymentMethod: editingMethod, accountHolderName: 'Ana García',
        accountNumber: 'ana@example.com', accountType: 'ahorro', isDefault: false,
        providerMetadata: JSON.stringify(metadata) as any,
      } : null} />);
  });
  trees.push(tree);
  return tree;
};
const press = async (tree: renderer.ReactTestRenderer, label: string) => {
  const node = tree.root.findAllByType(TouchableOpacity).find(n =>
    n.findAllByType(Text).some(t => t.props.children === label));
  expect(node).toBeDefined();
  await act(async () => { await node!.props.onPress(); });
};
const fill = (tree: renderer.ReactTestRenderer, placeholder: string, value: string) => {
  act(() => tree.root.findAllByType(TextInput).find(n => n.props.placeholder === placeholder)!.props.onChangeText(value));
};
const key = (tree: renderer.ReactTestRenderer) => tree.root.findAllByType(TextInput).find(n => n.props.placeholder === 'Celular con +57, NIT, correo o alias')!;
const prepare = async (value: string) => {
  const tree = render();
  await press(tree, 'Llave Bre-B');
  fill(tree, 'Titular de la cuenta asociada a la llave', 'Ana García');
  fill(tree, 'Celular con +57, NIT, correo o alias', value);
  await press(tree, 'Cuenta de Ahorros');
  return tree;
};
beforeEach(() => {
  jest.clearAllMocks();
  mockCreate.mockResolvedValue({ data: { createBankInfo: { success: true } } });
  mockUpdate.mockResolvedValue({ data: { updateBankInfo: { success: true } } });
});
afterEach(() => { act(() => trees.splice(0).forEach(tree => tree.unmount())); });

it.each(['+573001234567', '900123456-7', 'ana@example.com', '@ANA', '+receipts@example.com'])(
  'saves opaque Bre-B key %s with bank and account type', async value => {
    const tree = await prepare(value);
    expect(key(tree).props).toMatchObject({ keyboardType: 'default', maxLength: 254, autoCapitalize: 'none', autoCorrect: false });
    await press(tree, 'Agregar forma de cobro');
    expect(mockCreate).toHaveBeenCalledTimes(1);
    const variables = mockCreate.mock.calls[0][0].variables;
    expect(variables).toMatchObject({ accountNumber: value, accountType: 'ahorro' });
    expect(JSON.parse(variables.providerMetadata)).toEqual({ rail: 'BREB', bankCode: 'co_bancolombia' });
  },
);
it.each(['', '+13001234567', '+57300123', 'ana garcia', 'a'.repeat(255)])('rejects malformed or empty key %s before saving', async value => {
  const tree = await prepare(value);
  await press(tree, 'Agregar forma de cobro');
  expect(mockCreate).not.toHaveBeenCalled();
});
it('restores saved Bre-B metadata and updates without losing the key', async () => {
  const tree = render(true);
  expect(key(tree).props.value).toBe('ana@example.com');
  await press(tree, 'Guardar cambios');
  expect(mockUpdate.mock.calls[0][0].variables).toMatchObject({ bankInfoId: 'saved', accountNumber: 'ana@example.com', accountType: 'ahorro' });
  expect(JSON.parse(mockUpdate.mock.calls[0][0].variables.providerMetadata).rail).toBe('BREB');
});
it('clears the key when switching back to a traditional bank account and omits rail', async () => {
  const tree = render(true);
  await press(tree, 'Cuenta bancaria');
  const account = tree.root.findAllByType(TextInput).find(n => n.props.placeholder === 'Cuenta bancaria')!;
  expect(account.props.value).toBe('');
  expect(account.props.maxLength).toBe(11);
  fill(tree, 'Cuenta bancaria', '1234567890');
  await press(tree, 'Guardar cambios');
  expect(JSON.parse(mockUpdate.mock.calls[0][0].variables.providerMetadata)).toEqual({ bankCode: 'co_bancolombia' });
});
it('clears rail and key when changing payment methods', async () => {
  const tree = render(true);
  await press(tree, 'Bancolombia');
  await press(tree, 'Nequi');
  expect(key(tree)).toBeUndefined();
  expect(tree.root.findAllByType(TextInput).some(n => n.props.value === 'ana@example.com')).toBe(false);
});
it('clears rail and key when changing countries', async () => {
  const tree = render(true);
  await press(tree, 'Colombia');
  await press(tree, 'Perú');
  expect(key(tree)).toBeUndefined();
  expect(tree.root.findAllByType(TextInput).some(n => n.props.value === 'ana@example.com')).toBe(false);
});

it('explicitly clears metadata on edits when rail was the only metadata field', async () => {
  const tree = render(true, { rail: 'BREB' }, {});
  await press(tree, 'Cuenta bancaria');
  fill(tree, 'Cuenta bancaria', '1234567890');
  await press(tree, 'Guardar cambios');
  expect(mockUpdate.mock.calls[0][0].variables.providerMetadata).toBe('{}');
});
it('preserves the key when selecting the already selected Bre-B rail', async () => {
  const tree = render(true);
  await press(tree, 'Llave Bre-B');
  expect(key(tree).props.value).toBe('ana@example.com');
});

it('shows Bre-B as a separate payment method and opens the key form directly', async () => {
  const standalone = {
    ...mockMethod, id: 'breb', name: 'BREB', code: 'BREB', displayName: 'Bre-B',
    fieldSchema: { ...mockMethod.fieldSchema, defaultProviderMetadata: { bankCode: 'co_bancolombia', rail: 'BREB' } },
  };
  mockMethods.push(standalone);
  try {
    const tree = render();
    await press(tree, 'Bancolombia');
    await press(tree, 'Bre-B');
    expect(key(tree)).toBeDefined();
    fill(tree, 'Titular de la cuenta asociada a la llave', 'Ana García');
    fill(tree, 'Celular con +57, NIT, correo o alias', 'ana@example.com');
    await press(tree, 'Cuenta de Ahorros');
    await press(tree, 'Agregar forma de cobro');
    const variables = mockCreate.mock.calls[0][0].variables;
    expect(variables.rampPaymentMethodId).toBe('breb');
    expect(JSON.parse(variables.providerMetadata).rail).toBe('BREB');
    expect(tree.root.findAllByType(TouchableOpacity).some(n => n.props.accessibilityRole === 'radio')).toBe(false);
  } finally {
    mockMethods.pop();
  }
});
