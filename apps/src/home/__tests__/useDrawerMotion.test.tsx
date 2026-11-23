import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { drawerWidth, isSidewaysDrag, settlesOpen, useDrawerMotion } from '../useDrawerMotion';

describe('the menu follows the finger', () => {
  it('is as wide as most of the screen, up to a limit', () => {
    expect(drawerWidth(360)).toBe(310);
    expect(drawerWidth(430)).toBe(340);
    expect(drawerWidth(1024)).toBe(340);
  });

  it('a drag counts once it is clearly sideways: a scroll that wanders stays a scroll', () => {
    expect(isSidewaysDrag(40, 5, 'right')).toBe(true);
    expect(isSidewaysDrag(8, 0, 'right')).toBe(false); // barely moved
    expect(isSidewaysDrag(40, 60, 'right')).toBe(false); // mostly vertical
    expect(isSidewaysDrag(-40, 5, 'right')).toBe(false); // the other way
    expect(isSidewaysDrag(-40, 5, 'left')).toBe(true);
    expect(isSidewaysDrag(40, 5, 'left')).toBe(false);
  });

  it('let go, it settles where the drag was heading: past a third of the way, or a flick', () => {
    const width = 310;
    // Opening.
    expect(settlesOpen({ dx: 150, vx: 0, width, wasOpen: false })).toBe(true);
    expect(settlesOpen({ dx: 60, vx: 0, width, wasOpen: false })).toBe(false);
    expect(settlesOpen({ dx: 60, vx: 0.8, width, wasOpen: false })).toBe(true);
    // Closing.
    expect(settlesOpen({ dx: -150, vx: 0, width, wasOpen: true })).toBe(false);
    expect(settlesOpen({ dx: -40, vx: 0, width, wasOpen: true })).toBe(true);
    expect(settlesOpen({ dx: -40, vx: -0.8, width, wasOpen: true })).toBe(false);
  });
});

describe('opening and closing', () => {
  let motion!: ReturnType<typeof useDrawerMotion>;
  const setIsOpen = jest.fn();
  const Probe = ({ isOpen }: { isOpen: boolean }) => {
    motion = useDrawerMotion(isOpen, setIsOpen, 310);
    return null;
  };

  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it('is not drawn until it opens, and stops being drawn once it has slid away', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<Probe isOpen={false} />); });
    await act(async () => { jest.runAllTimers(); });
    expect(motion.mounted).toBe(false);

    await act(async () => { tree.update(<Probe isOpen />); });
    expect(motion.mounted).toBe(true);
    await act(async () => { jest.runAllTimers(); });
    expect(motion.mounted).toBe(true);

    await act(async () => { tree.update(<Probe isOpen={false} />); });
    // Still drawn while it slides away.
    expect(motion.mounted).toBe(true);
    await act(async () => { jest.runAllTimers(); });
    expect(motion.mounted).toBe(false);
    await act(async () => tree.unmount());
  });

  it('offers one gesture for the conversation and one for the open menu', async () => {
    let tree!: renderer.ReactTestRenderer;
    await act(async () => { tree = renderer.create(<Probe isOpen={false} />); });
    for (const gesture of [motion.openGesture, motion.closeGesture]) {
      expect(typeof gesture.onMoveShouldSetResponder).toBe('function');
      expect(typeof gesture.onResponderRelease).toBe('function');
    }
    // Stable across renders: the conversation is not re-wired on every update.
    const first = motion.openGesture;
    await act(async () => { tree.update(<Probe isOpen={false} />); });
    expect(motion.openGesture).toBe(first);
    await act(async () => tree.unmount());
  });
});
