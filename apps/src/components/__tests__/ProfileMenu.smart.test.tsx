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

const render = async (selectedAccount: string, onSwitch = jest.fn()) => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(
      <ProfileMenu
        visible
        onClose={() => {}}
        accounts={accounts}
        selectedAccount={selectedAccount}
        onAccountSwitch={onSwitch}
        onCreateBusinessAccount={() => {}}
      />,
    );
  });
  const rows = tree.root.findAllByType(TouchableOpacity)
    .map((n) => n.props.accessibilityLabel)
    .filter((l) => typeof l === 'string' && l.includes(','));
  return { tree, rows };
};

it('lists personal and business only: a Cuenta inteligente, own or inherited, is never an account to switch to', async () => {
  const { tree, rows } = await render('personal_0');
  expect(rows).toEqual(['Julia, Personal', 'Tienda, Negocio']);
  await act(async () => tree.unmount());
});

it('inside a Cuenta inteligente the menu still lists none of them, and the personal row takes the person back', async () => {
  const onSwitch = jest.fn();
  const { tree, rows } = await render('smart_0', onSwitch);
  expect(rows).toEqual(['Julia, Personal', 'Tienda, Negocio']);
  const personal = tree.root.findAllByType(TouchableOpacity)
    .find((n) => n.props.accessibilityLabel === 'Julia, Personal')!;
  await act(async () => { personal.props.onPress(); });
  expect(onSwitch).toHaveBeenCalledWith('personal_0');
  await act(async () => tree.unmount());
});
