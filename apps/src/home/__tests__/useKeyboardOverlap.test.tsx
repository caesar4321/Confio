// Android: the conversation steps above the keyboard by what it really covers.
import React from 'react';
import { Keyboard, Platform, View } from 'react-native';
import renderer, { act } from 'react-test-renderer';
import { overlapOf, useKeyboardOverlap } from '../useKeyboardOverlap';

let latest: ReturnType<typeof useKeyboardOverlap>;
let bottom = 800;   // where the view's bottom is on screen
function Probe() {
  latest = useKeyboardOverlap();
  return <View ref={latest.ref} onLayout={latest.onLayout} />;
}
const listeners: Record<string, (e: any) => void> = {};
const original = Platform.OS;

beforeEach(() => {
  bottom = 800;
  jest.spyOn(Keyboard, 'addListener').mockImplementation(((event: string, cb: (e: any) => void) => {
    listeners[event] = cb;
    return { remove: jest.fn() };
  }) as any);
});
afterEach(() => {
  Object.defineProperty(Platform, 'OS', { value: original, configurable: true });
  jest.restoreAllMocks();
});
const mount = async (os: string) => {
  Object.defineProperty(Platform, 'OS', { value: os, configurable: true });
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  // The test renderer's view measures nothing: give it a place on the screen.
  // (pageY from the top of the screen: here the view starts under a 40-point status bar.)
  (latest.ref as any).current = { measure: (cb: (...a: number[]) => void) => cb(0, 0, 400, bottom - 40, 0, 40) };
  return tree;
};

it('is what the keyboard covers, and never less than nothing', () => {
  expect(overlapOf(800, null)).toBe(0);
  expect(overlapOf(800, 500)).toBe(300);
  expect(overlapOf(500, 500)).toBe(0);
  expect(overlapOf(476, 500)).toBe(0);      // the system already made room, and then some
  expect(overlapOf(NaN, 500)).toBe(0);
  // Never more than the keyboard is tall, whatever the positions say.
  expect(overlapOf(800, 300, 260)).toBe(260);
});

it('edge to edge (the window is not resized): the view steps above the keyboard, and back when it goes', async () => {
  const tree = await mount('android');
  expect(latest.overlap).toBe(0);
  await act(async () => { listeners.keyboardDidShow({ endCoordinates: { screenY: 500, height: 300 } }); });
  expect(latest.overlap).toBe(300);
  await act(async () => { listeners.keyboardDidHide({}); });
  expect(latest.overlap).toBe(0);
  await act(async () => tree.unmount());
});

it('an Android that resizes the window itself gets nothing added twice', async () => {
  const tree = await mount('android');
  await act(async () => { listeners.keyboardDidShow({ endCoordinates: { screenY: 500, height: 300 } }); });
  expect(latest.overlap).toBe(300);
  // The system's resize lands a moment later: the view's bottom is now at the keyboard's top.
  bottom = 500;
  await act(async () => { latest.onLayout?.(); });
  expect(latest.overlap).toBe(0);
  await act(async () => tree.unmount());
});

it('iOS is left to KeyboardAvoidingView', async () => {
  const tree = await mount('ios');
  expect(latest.onLayout).toBeUndefined();
  expect(Object.keys(listeners).length ? latest.overlap : 0).toBe(0);
  await act(async () => tree.unmount());
});
