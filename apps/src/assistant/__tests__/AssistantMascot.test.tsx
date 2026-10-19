import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockRepeat = jest.fn((animation: unknown, _reps: number) => animation);
jest.mock('react-native-reanimated', () => {
  const { View } = require('react-native');
  return {
    __esModule: true,
    default: { View },
    useSharedValue: (v: number) => ({ value: v }),
    useAnimatedStyle: (fn: () => object) => fn(),
    withRepeat: (a: unknown, reps: number) => mockRepeat(a, reps),
    withSequence: (...a: unknown[]) => a,
    withTiming: (to: number) => to,
    cancelAnimation: () => {},
    Easing: { inOut: (e: unknown) => e, quad: 'quad' },
  };
});

import AssistantMascot from '../AssistantMascot';

const repsFor = async (props: React.ComponentProps<typeof AssistantMascot>) => {
  mockRepeat.mockClear();
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AssistantMascot {...props} />); });
  const reps = mockRepeat.mock.calls.map((c) => c[1]);
  await act(async () => tree.unmount());
  return reps;
};

// An endless idle bob redrew the whole window every frame (240 fps, ~85%
// CPU on Julian's phone) wherever the bubble showed. Calm moods must end.
describe('AssistantMascot animation budget', () => {
  it.each(['idle', 'happy'] as const)('%s never repeats forever (built-in and pet photo)', async (mood) => {
    for (const props of [{ kind: 'DOG' as const }, { kind: 'CUSTOM' as const, imageUrl: 'https://x/pet.jpg' }]) {
      const reps = await repsFor({ ...props, mood });
      expect(reps.length).toBeGreaterThan(0);
      expect(reps.every((r) => r > 0)).toBe(true);
    }
  });

  it.each(['talking', 'listening', 'thinking'] as const)('%s keeps moving while it lasts', async (mood) => {
    const reps = await repsFor({ kind: 'CUSTOM', imageUrl: 'https://x/pet.jpg', mood });
    expect(reps).toContain(-1);
  });
});
