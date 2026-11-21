import { returnToPersonal, resetMocks } from '../../components/smartAccount/testing/mocks';
import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { tap, text } from '../../components/smartAccount/testing/fixtures';
import { SMART_CONTEXT_ASSISTANT_COPY, SmartContextAssistantNotice, isSmartContext } from '../SmartContextNotice';

beforeEach(() => resetMocks());

it('recognizes own and inherited Cuenta inteligente contexts only', () => {
  expect(isSmartContext({ type: 'smart' })).toBe(true);
  expect(isSmartContext({ type: 'SMART' })).toBe(true);
  expect(isSmartContext({ type: 'personal' })).toBe(false);
  expect(isSmartContext({ type: 'business' })).toBe(false);
  expect(isSmartContext(null)).toBe(false);
});

it('says to switch and switches to the personal account', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<SmartContextAssistantNotice />); });
  expect(text(tree)).toContain(SMART_CONTEXT_ASSISTANT_COPY);
  expect(SMART_CONTEXT_ASSISTANT_COPY).toBe('Cambia a tu cuenta personal para hablar con Confío IA');
  await tap(tree, 'assistant-switch-personal');
  expect(returnToPersonal).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});
