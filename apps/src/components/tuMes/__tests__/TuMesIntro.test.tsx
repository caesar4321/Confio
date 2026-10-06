import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { AccessibilityInfo, Animated, Text } from 'react-native';
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-svg', () => {
  const R = require('react');
  const C = (p: any) => R.createElement('Svg', p, p.children);
  return { __esModule: true, default: C, Defs: C, LinearGradient: C, Rect: C, Stop: C };
});
import { TuMesIntro } from '../TuMesIntro';

// Animations finish instantly in tests (callbacks run), timers stay real.
const instant = () => ({ start: (cb?: (r: { finished: boolean }) => void) => cb?.({ finished: true }), stop: jest.fn(), reset: jest.fn() }) as any;
jest.spyOn(Animated, 'timing').mockImplementation(instant);
jest.spyOn(Animated, 'spring').mockImplementation(instant);
jest.spyOn(Animated, 'parallel').mockImplementation(instant);
jest.spyOn(Animated, 'sequence').mockImplementation(instant);

const summary = {
  year: 2026, month: 10, timezone: 'UTC', previousIsPartial: true,
  current: { incomeUsd: '215.00', spendingUsd: '176.00', topUpsUsd: '0', withdrawalsUsd: '0', savingsNetUsd: '0',
    investmentNetUsd: '0', movementCount: 3, spendingByCategory: [] },
  previous: { incomeUsd: '0', spendingUsd: '0', topUpsUsd: '0', withdrawalsUsd: '0', savingsNetUsd: '0',
    investmentNetUsd: '0', movementCount: 0, spendingByCategory: [] },
  counterparties: [],
} as any;

const texts = (t: renderer.ReactTestRenderer) => t.root.findAllByType(Text).map((n) => [].concat(n.props.children).join(''));

function a11y(reduce: boolean, reader = false) {
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(reduce);
  jest.spyOn(AccessibilityInfo, 'isScreenReaderEnabled').mockResolvedValue(reader);
}

async function mount(el: React.ReactElement) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(el); });
  return tree;
}

it('fills the screen with the month, the result and the two flows', async () => {
  a11y(false);
  const onDone = jest.fn();
  const tree = await mount(<TuMesIntro month={10} summary={summary} masked={false} onDone={onDone} />);
  expect(tree.root.findAll((n) => typeof n.type === 'string' && n.props.testID === 'tumes-intro')).toHaveLength(1);
  const all = texts(tree);
  expect(all).toContain('Octubre');
  expect(all).toContain('↓ Entró US$215');
  expect(all).toContain('↑ Salió US$176');
  expect(onDone).not.toHaveBeenCalled();
  act(() => tree.unmount());
});

it('tap anywhere skips it', async () => {
  a11y(false);
  const onDone = jest.fn();
  const tree = await mount(<TuMesIntro month={10} summary={summary} masked={false} onDone={onDone} />);
  act(() => { tree.root.findAll((n) => n.props.testID === 'tumes-intro-skip' && n.props.onPress)[0].props.onPress(); });
  expect(onDone).toHaveBeenCalledTimes(1);
  act(() => tree.unmount());
});

it('masks amounts with the balance hidden', async () => {
  a11y(false);
  const tree = await mount(<TuMesIntro month={10} summary={summary} masked onDone={jest.fn()} />);
  expect(texts(tree).join(' ')).not.toMatch(/US\$\d/);
  act(() => tree.unmount());
});

it.each([[true, false], [false, true]])('never shows with Reduce Motion (%s) or a screen reader (%s)', async (reduce, reader) => {
  a11y(reduce, reader);
  const onDone = jest.fn();
  const tree = await mount(<TuMesIntro month={10} summary={summary} masked={false} onDone={onDone} />);
  expect(tree.toJSON()).toBeNull();
  expect(onDone).toHaveBeenCalledTimes(1);
});
