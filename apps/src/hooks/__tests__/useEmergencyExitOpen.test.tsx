import React from 'react';
import { act, create, ReactTestRenderer } from 'react-test-renderer';
import { AppState, Text } from 'react-native';

const mockReadHeartbeat = jest.fn();
jest.mock('../../services/emergencyExit/heartbeat', () => ({ readHeartbeat: () => mockReadHeartbeat() }));
import { useEmergencyExitOpen, EXIT_RECHECK_MS } from '../useEmergencyExitOpen';

const Probe = ({ active }: { active: boolean }) => <Text>{useEmergencyExitOpen(active) ? 'open' : 'closed'}</Text>;
const shown = (v: ReactTestRenderer) => v.root.findByType(Text).props.children;
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

beforeEach(() => { jest.useFakeTimers(); mockReadHeartbeat.mockReset(); });
afterEach(() => { jest.useRealTimers(); });

it('a failed read is retried while visible — the exit appears once the chain says open', async () => {
  mockReadHeartbeat.mockResolvedValueOnce({ state: 'unreachable' }).mockResolvedValue({ state: 'open' });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  await flush();
  expect(shown(v)).toBe('closed');
  await act(async () => { jest.advanceTimersByTime(EXIT_RECHECK_MS); });
  await flush();
  expect(shown(v)).toBe('open');
  act(() => v.unmount());
});

it('keeps checking while open: if Confío beats again the exit disappears', async () => {
  mockReadHeartbeat.mockResolvedValueOnce({ state: 'open' }).mockResolvedValue({ state: 'alive' });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  await flush();
  expect(shown(v)).toBe('open');
  await act(async () => { jest.advanceTimersByTime(EXIT_RECHECK_MS); });
  await flush();
  expect(shown(v)).toBe('closed');
  act(() => v.unmount());
});

it('re-checks nothing while inactive, and never carries "open" into the next session', async () => {
  mockReadHeartbeat.mockResolvedValue({ state: 'open' });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  await flush();
  const calls = mockReadHeartbeat.mock.calls.length;
  await act(async () => { v.update(<Probe active={false} />); });
  expect(shown(v)).toBe('closed');
  await act(async () => { jest.advanceTimersByTime(EXIT_RECHECK_MS * 3); });
  expect(mockReadHeartbeat).toHaveBeenCalledTimes(calls);
  act(() => v.unmount());
});

it('a slow older read cannot overwrite a newer one', async () => {
  // While a read is in flight the timer waits; a foreground return is what
  // starts an overlapping, newer read.
  let onAppState!: (s: string) => void;
  const original = AppState.addEventListener;
  (AppState as any).addEventListener = (_e: any, cb: any) => {
    onAppState = cb;
    return { remove: jest.fn() };
  };
  let resolveSlow!: (v: unknown) => void;
  mockReadHeartbeat
    .mockImplementationOnce(() => new Promise((r) => { resolveSlow = r; })) // slow first read
    .mockResolvedValue({ state: 'open' });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  await act(async () => { onAppState('active'); });
  await flush();
  expect(shown(v)).toBe('open');
  await act(async () => { resolveSlow({ state: 'unreachable' }); });
  await flush();
  expect(shown(v)).toBe('open');
  act(() => v.unmount());
  (AppState as any).addEventListener = original;
});

it('a new session starts closed until its own read says open', async () => {
  mockReadHeartbeat.mockResolvedValueOnce({ state: 'open' }).mockResolvedValue({ state: 'alive' });
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  await flush();
  expect(shown(v)).toBe('open');
  await act(async () => { v.update(<Probe active={false} />); });
  await act(async () => { v.update(<Probe active />); });
  expect(shown(v)).toBe('closed');
  await flush();
  expect(shown(v)).toBe('closed'); // Confío beat again
  act(() => v.unmount());
});

it('a read slower than the recheck interval still lands (no starvation, no stacking)', async () => {
  // Every read takes 40s — e.g. the first public RPCs hang until their abort.
  mockReadHeartbeat.mockImplementation(() => new Promise((r) => setTimeout(() => r({ state: 'open' }), 40_000)));
  let v!: ReactTestRenderer;
  await act(async () => { v = create(<Probe active />); });
  for (let i = 0; i < 5; i++) {
    await act(async () => { jest.advanceTimersByTime(EXIT_RECHECK_MS); });
    await flush();
  }
  expect(shown(v)).toBe('open');
  // Ticks were skipped while a read was in flight: not one new read per tick.
  expect(mockReadHeartbeat.mock.calls.length).toBeLessThanOrEqual(3);
  act(() => v.unmount());
});
