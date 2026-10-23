import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Pressable } from 'react-native';
import { InvestorLockCard, isLocked } from '../InvestorLockCard';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');

const textOf = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((node) => typeof node.props.children === 'string').map((node) => node.props.children).join('|');

test('only the three lock states lock', () => {
  expect(['self', 'open'].map((a) => isLocked(a as any))).toEqual([false, false]);
  expect(['target_hidden', 'viewer_hidden', 'viewer_unverified'].map((a) => isLocked(a as any))).toEqual([true, true, true]);
  expect(isLocked(null)).toBe(false);
});

test('a hidden viewer is offered to publish', () => {
  const onPublish = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<InvestorLockCard access="viewer_hidden" onPublish={onPublish} onVerify={jest.fn()} />); });
  expect(textOf(tree)).toContain('Hacer público');
  act(() => { tree.root.findByType(Pressable).props.onPress(); });
  expect(onPublish).toHaveBeenCalled();
});

test('an unverified viewer is sent to verify', () => {
  const onVerify = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<InvestorLockCard access="viewer_unverified" onPublish={jest.fn()} onVerify={onVerify} />); });
  expect(textOf(tree)).toContain('Verificar identidad');
  act(() => { tree.root.findByType(Pressable).props.onPress(); });
  expect(onVerify).toHaveBeenCalled();
});

test('a private target has no action', () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<InvestorLockCard access="target_hidden" />); });
  expect(textOf(tree)).toContain('Portafolio privado');
  expect(tree.root.findAllByType(Pressable)).toHaveLength(0);
});
