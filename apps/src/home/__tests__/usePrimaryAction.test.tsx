import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockNavigate = jest.fn();
let mockAccount: any = null;
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));

import { usePrimaryAction, type PrimaryAction } from '../usePrimaryAction';

let action: PrimaryAction | null = null;
const Probe = () => {
  action = usePrimaryAction();
  return null;
};
async function actionFor(account: any) {
  mockAccount = account;
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  const result = action;
  await act(async () => tree.unmount());
  return result;
}

beforeEach(() => mockNavigate.mockClear());

it('a person pays; the scanner opens as a stack screen with its back arrow', async () => {
  const primary = await actionFor({ type: 'personal' });
  expect(primary?.kind).toBe('pay');
  primary?.onPress();
  expect(mockNavigate).toHaveBeenCalledWith('Scan', { mode: 'pagar' });
  // No account yet reads as personal.
  expect((await actionFor(null))?.kind).toBe('pay');
});

it('a business charges', async () => {
  const primary = await actionFor({ type: 'business' });
  expect(primary?.kind).toBe('charge');
  primary?.onPress();
  expect(mockNavigate).toHaveBeenCalledWith('Charge');
});

it('an employee gets what the role allows: Cobrar, else Pagar, else nothing', async () => {
  const employee = (employeePermissions: object) => ({ type: 'business', isEmployee: true, employeePermissions });
  expect((await actionFor(employee({ acceptPayments: true, sendFunds: true })))?.kind).toBe('charge');
  expect((await actionFor(employee({ acceptPayments: false, sendFunds: true })))?.kind).toBe('pay');
  expect(await actionFor(employee({ acceptPayments: false, sendFunds: false }))).toBeNull();
  expect(await actionFor(employee({}))).toBeNull();
});

it('a Cuenta inteligente context neither pays nor charges', async () => {
  expect(await actionFor({ type: 'smart', index: 0 })).toBeNull();
});
