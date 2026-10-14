import React from 'react';
import renderer, {act} from 'react-test-renderer';
import {useSettlementDetails} from '../useSettlementStatus';
import {apolloClient} from '../../apollo/client';

jest.mock('@apollo/client', () => ({gql: (parts: TemplateStringsArray, query: string) => query}));
jest.mock('../../apollo/client', () => ({apolloClient: {query: jest.fn()}}));
const query = apolloClient.query as jest.Mock;
const id = 'da847ed098a44dd6ac1d72a34f845dee';
const timestamp = '2026-08-28T11:17:09Z';
let snapshot: ReturnType<typeof useSettlementDetails>;
let root: ReturnType<typeof renderer.create>;
function Probe({operation = id, status = 'SUBMITTED', date}: {operation?: string; status?: string; date?: string}) {
  snapshot = useSettlementDetails('send', operation, status, date);
  return null;
}
beforeEach(() => {jest.useFakeTimers(); query.mockReset();});
afterEach(async () => {if (root) await act(async () => root.unmount()); jest.useRealTimers();});

it('retrieves a missing date even for an already confirmed operation', async () => {
  query.mockResolvedValue({data: {sendTransaction: {status: 'CONFIRMED', createdAt: timestamp}}});
  await act(async () => {root = renderer.create(<Probe status="CONFIRMED" />);});
  expect(query).toHaveBeenCalledWith(expect.objectContaining({variables: {id}, fetchPolicy: 'network-only'}));
  expect(snapshot).toMatchObject({status: 'CONFIRMED', createdAt: timestamp});
  await act(async () => {jest.advanceTimersByTime(10000);});
  expect(query).toHaveBeenCalledTimes(1);
});
it('updates pending receipt state after server confirmation', async () => {
  query.mockResolvedValueOnce({data: {sendTransaction: {status: 'SUBMITTED', createdAt: timestamp}}})
    .mockResolvedValueOnce({data: {sendTransaction: {status: 'CONFIRMED', createdAt: timestamp}}});
  await act(async () => {root = renderer.create(<Probe />);});
  expect(snapshot.status).toBe('SUBMITTED');
  await act(async () => {jest.advanceTimersByTime(2000);});
  expect(snapshot.status).toBe('CONFIRMED');
});
it('does not invent confirmation or date on network failure and stops after its deadline', async () => {
  query.mockRejectedValue(new Error('offline'));
  await act(async () => {root = renderer.create(<Probe />);});
  for (let i = 0; i < 46; i++) await act(async () => {jest.advanceTimersByTime(2000);});
  const calls = query.mock.calls.length;
  expect(calls).toBeLessThanOrEqual(46);
  await act(async () => {jest.advanceTimersByTime(10000);});
  expect(query).toHaveBeenCalledTimes(calls);
  expect(snapshot).toMatchObject({status: 'SUBMITTED', createdAt: undefined});
});
it('ignores an old operation response after the receipt changes', async () => {
  let resolveOld!: (value: unknown) => void;
  query.mockImplementationOnce(() => new Promise(resolve => {resolveOld = resolve;}))
    .mockResolvedValue({data: {sendTransaction: {status: 'FAILED', createdAt: timestamp}}});
  await act(async () => {root = renderer.create(<Probe />);});
  await act(async () => {root.update(<Probe operation="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" />);});
  await act(async () => {resolveOld({data: {sendTransaction: {status: 'CONFIRMED', createdAt: '2026-01-01T00:00:00Z'}}});});
  expect(snapshot).toMatchObject({status: 'FAILED', createdAt: timestamp});
});
it('does not refetch complete terminal metadata', async () => {
  await act(async () => {root = renderer.create(<Probe status="confirmed" date={timestamp} />);});
  await act(async () => {jest.advanceTimersByTime(10000);});
  expect(query).not.toHaveBeenCalled();
});
