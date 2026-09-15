import React from 'react';
import renderer, {act} from 'react-test-renderer';

let mockAccounts: any[] = [];
jest.mock('../../apollo/queries', () => ({GET_MY_PAYMENT_ACCOUNTS: 'accounts'}));
jest.mock('@apollo/client', () => ({
  useQuery: () => ({data: {myPaymentAccounts: mockAccounts}, loading: false, refetch: jest.fn()}),
}));
import {useLocalPaymentAccounts} from '../useLocalPaymentAccounts';

const account = (kind: string, status: string, displayValue: string) => ({
  internalId: `${kind}-${status}`, provider: 'cobre', country: 'COL', asset: 'COP', status: 'active',
  ownershipStructure: 'omnibus_subledger', availableBalance: '0', capabilities: [],
  fundingInstructions: [{internalId: 'instruction', kind, status, displayValue, holderDisplayName: ''}],
});

function receivableOf(accounts: any[]) {
  mockAccounts = accounts;
  let result: any[] = [];
  function Probe() {
    result = useLocalPaymentAccounts().receivable;
    return null;
  }
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<Probe />); });
  act(() => { tree.unmount(); });
  return result;
}

it('keeps an active Bre-B key whose value the server withholds', () => {
  const hidden = account('breb_key', 'active', '');
  expect(receivableOf([hidden])).toEqual([hidden]);
});

it('still needs a value for other instructions, and an active key', () => {
  expect(receivableOf([account('clabe', 'active', ''), account('breb_key', 'pending', '')])).toEqual([]);
  const clabe = account('clabe', 'active', '012345678901234567');
  expect(receivableOf([clabe])).toEqual([clabe]);
});
