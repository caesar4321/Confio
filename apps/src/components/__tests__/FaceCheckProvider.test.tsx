import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Modal, Pressable } from 'react-native';
import { FaceCheckProvider } from '../FaceCheckProvider';
import { registerFaceCheckPresenter, runFaceCapture } from '../../services/faceStepUp';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../services/faceStepUp', () => ({
  registerFaceCheckPresenter: jest.fn(),
  runFaceCapture: jest.fn(),
}));
const mockNav = { route: 'Home', listeners: [] as Array<() => void> };
jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: {
    isReady: () => true,
    navigate: jest.fn((name: string) => { mockNav.route = name; }),
    getCurrentRoute: () => ({ name: mockNav.route }),
    addListener: (_event: string, fn: () => void) => {
      mockNav.listeners.push(fn);
      return () => { mockNav.listeners = mockNav.listeners.filter(l => l !== fn); };
    },
  },
}));

beforeEach(() => { jest.useFakeTimers(); jest.clearAllMocks(); });
afterEach(() => { jest.useRealTimers(); });

test('Back during success cannot approve the next queued purpose', async () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<FaceCheckProvider><></></FaceCheckProvider>); });
  const present = jest.mocked(registerFaceCheckPresenter).mock.calls[0][0]!;
  const first = jest.fn();
  const second = jest.fn();
  act(() => {
    void present('withdrawal').then(first);
    void present('emergency_exit').then(second);
  });
  jest.mocked(runFaceCapture).mockResolvedValueOnce({ outcome: 'passed' });
  await act(async () => { await tree.root.findAllByType(Pressable)[0].props.onPress(); });
  await act(async () => {
    tree.root.findByType(Modal).props.onRequestClose();
    jest.advanceTimersByTime(1300);
  });
  expect(first).toHaveBeenCalledWith(true);
  expect(second).not.toHaveBeenCalled();
  expect(runFaceCapture).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
  expect(second).toHaveBeenCalledWith(false);
});

test('unmount settles active and queued callers without late success', async () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<FaceCheckProvider><></></FaceCheckProvider>); });
  const present = jest.mocked(registerFaceCheckPresenter).mock.calls[0][0]!;
  const first = jest.fn();
  const second = jest.fn();
  act(() => {
    void present('withdrawal').then(first);
    void present('emergency_exit').then(second);
  });
  await act(async () => { tree.unmount(); jest.advanceTimersByTime(2000); });
  expect(first).toHaveBeenCalledWith(false);
  expect(second).toHaveBeenCalledWith(false);
});

test('rapid taps launch only one capture and late completion after unmount is ignored', async () => {
  let complete!: (result: { outcome: 'passed' }) => void;
  jest.mocked(runFaceCapture).mockReturnValueOnce(new Promise(resolve => { complete = resolve; }));
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<FaceCheckProvider><></></FaceCheckProvider>); });
  const present = jest.mocked(registerFaceCheckPresenter).mock.calls[0][0]!;
  const settled = jest.fn();
  act(() => { void present('withdrawal').then(settled); });
  const start = tree.root.findAllByType(Pressable)[0].props.onPress;
  act(() => { void start(); void start(); });
  expect(runFaceCapture).toHaveBeenCalledTimes(1);
  await act(async () => { tree.unmount(); });
  await act(async () => { complete({ outcome: 'passed' }); });
  await act(async () => { jest.advanceTimersByTime(2000); });
  expect(settled).toHaveBeenCalledTimes(1);
  expect(settled).toHaveBeenCalledWith(false);
});

test('privacy policy opens in the app and the pending check comes back', async () => {
  const { navigationRef } = require('../../navigation/RootNavigation');
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<FaceCheckProvider><></></FaceCheckProvider>); });
  const present = jest.mocked(registerFaceCheckPresenter).mock.calls[0][0]!;
  const settled = jest.fn();
  act(() => { void present('withdrawal').then(settled); });
  const link = tree.root.findAll(n => n.props.accessibilityRole === 'link' && typeof n.props.onPress === 'function')[0];
  act(() => { link.props.onPress(); });
  expect(navigationRef.navigate).toHaveBeenCalledWith('LegalDocument', { docType: 'privacy' });
  expect(tree.root.findByType(Modal).props.visible).toBe(false);
  act(() => { mockNav.route = 'Home'; mockNav.listeners.forEach(l => l()); });
  expect(tree.root.findByType(Modal).props.visible).toBe(true);
  expect(settled).not.toHaveBeenCalled();
  await act(async () => { tree.unmount(); });
});
