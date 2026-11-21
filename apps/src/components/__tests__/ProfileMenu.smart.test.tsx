import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { TouchableOpacity } from 'react-native';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: null, isUserProfileLoading: false }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ isLoading: false }) }));
import { ProfileMenu } from '../ProfileMenu';
import { buildSmartStoredAccounts } from '../../utils/smartAccounts';

const smart = buildSmartStoredAccounts(
  { status: 'active', contractAddress: '0xc' },
  [{ inheritedAccountId: 'i1', contractAddress: '0xd', fromName: 'Luis', inheritedAt: '2026-11-01T00:00:00Z' }],
);
const accounts: any[] = [
  { id: 'personal_0', name: 'Julia', type: 'personal', avatar: 'J' },
  { id: 'business_7_0', name: 'Tienda', type: 'business', avatar: 'T' },
  ...smart,
];

it('lists the Cuenta inteligente third and an inherited one with its "heredada" label', async () => {
  const onSwitch = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(
      <ProfileMenu
        visible
        onClose={() => {}}
        accounts={accounts}
        selectedAccount="personal_0"
        onAccountSwitch={onSwitch}
        onCreateBusinessAccount={() => {}}
      />,
    );
  });
  const rows = tree.root.findAllByType(TouchableOpacity)
    .map((n) => n.props.accessibilityLabel)
    .filter((l) => typeof l === 'string' && l.includes(','));
  expect(rows).toEqual([
    'Julia, Personal',
    'Tienda, Negocio',
    'Cuenta inteligente, Tu cuenta',
    'Cuenta de Luis, Cuenta inteligente · heredada',
  ]);
  const smartRow = tree.root.findAllByType(TouchableOpacity)
    .find((n) => n.props.accessibilityLabel === 'Cuenta inteligente, Tu cuenta')!;
  await act(async () => { smartRow.props.onPress(); });
  expect(onSwitch).toHaveBeenCalledWith('smart_0');
  await act(async () => tree.unmount());
});
