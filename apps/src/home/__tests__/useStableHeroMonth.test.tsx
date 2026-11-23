import React from 'react';
import renderer, { act } from 'react-test-renderer';
import type { HeroMonthState } from '../../hooks/useMonthHeroLine';
import { useStableHeroMonth } from '../useStableHeroMonth';

let out!: HeroMonthState;
const Probe = ({ state }: { state: HeroMonthState }) => {
  out = useStableHeroMonth(state);
  return null;
};
const summary = { year: 2026, month: 11, current: { incomeUsd: '340', spendingUsd: '185' } } as any;

it('a new object with the same content, as the month hook returns on every render, keeps one identity', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe state={{ kind: 'month', summary }} />); });
  const first = out;
  expect(first).toEqual({ kind: 'month', summary });
  for (let i = 0; i < 3; i += 1) {
    await act(async () => { tree.update(<Probe state={{ kind: 'month', summary }} />); });
    expect(out).toBe(first);
  }
  // A new answer for the month is a new object.
  const next = { ...summary, current: { incomeUsd: '400', spendingUsd: '185' } };
  await act(async () => { tree.update(<Probe state={{ kind: 'month', summary: next }} />); });
  expect(out).not.toBe(first);
  expect(out).toEqual({ kind: 'month', summary: next });
  await act(async () => tree.unmount());
});

it('the states without a summary are stable too, and change with the state', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe state={{ kind: 'loading' }} />); });
  const loading = out;
  await act(async () => { tree.update(<Probe state={{ kind: 'loading' }} />); });
  expect(out).toBe(loading);
  await act(async () => { tree.update(<Probe state={{ kind: 'invite' }} />); });
  expect(out).toEqual({ kind: 'invite' });
  await act(async () => { tree.update(<Probe state={{ kind: 'hidden' }} />); });
  expect(out).toEqual({ kind: 'hidden' });
  await act(async () => tree.unmount());
});
