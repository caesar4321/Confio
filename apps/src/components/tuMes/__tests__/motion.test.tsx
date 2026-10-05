import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { AccessibilityInfo, Animated, Text } from 'react-native';
import { Grow, Rise, RISE_STAGGER_MS } from '../motion';

const timing = jest.spyOn(Animated, 'timing');

beforeEach(() => {
  timing.mockReset();
  timing.mockImplementation(() => ({ start: jest.fn(), stop: jest.fn(), reset: jest.fn() }) as any);
});

async function mount(el: React.ReactElement) {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(el); });
  return tree;
}

it('rises and grows once, staggered, on the native driver (transforms + opacity only)', async () => {
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(false);
  const tree = await mount(<>
    <Rise index={2}><Text>card</Text></Rise>
    <Grow delay={150}><Text>bar</Text></Grow>
  </>);
  const configs = timing.mock.calls.map((c) => c[1] as any);
  expect(configs.map((c) => c.delay)).toEqual([2 * RISE_STAGGER_MS, 150]);
  expect(configs.every((c) => c.useNativeDriver === true && c.toValue === 1)).toBe(true);
  act(() => tree.unmount());
});

it('Reduce Motion: no animation at all, content in its final place', async () => {
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);
  const tree = await mount(<Rise index={1}><Text>card</Text></Rise>);
  expect(timing).not.toHaveBeenCalled();
  act(() => tree.unmount());
});
