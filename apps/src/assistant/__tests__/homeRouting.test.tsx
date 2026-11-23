// The conversation home: a request for Confio Assistant goes to the
// conversation on screen instead of opening the floating box.
import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('../../navigation/RootNavigation', () => ({
  navigationRef: { getCurrentRoute: () => ({ name: 'Home' }), addListener: () => () => {} },
}));

import { AssistantProvider, useAssistant } from '../AssistantContext';

let assistant!: ReturnType<typeof useAssistant>;
const Probe = () => {
  assistant = useAssistant();
  return null;
};

async function mount() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<AssistantProvider><Probe /></AssistantProvider>); });
  return tree;
}

it('opens the box as before when Inicio is not the conversation on screen', async () => {
  const tree = await mount();
  await act(async () => { assistant.open({ prompt: 'hola' }); });
  expect(assistant.isOpen).toBe(true);
  expect(assistant.openSeq).toBe(1);
  expect(assistant.homeSeq).toBe(0);
  await act(async () => tree.unmount());
});

it('hands the request to the home conversation while it is on screen', async () => {
  const tree = await mount();
  await act(async () => { assistant.setHomeActive(true); });
  expect(assistant.homeActive).toBe(true);

  await act(async () => { assistant.open({ prompt: 'Abre QR para pagar' }); });
  expect(assistant.isOpen).toBe(false);
  expect(assistant.openSeq).toBe(0);
  expect(assistant.homeSeq).toBe(1);
  // The conversation reads the request exactly as the box would.
  let prompt: string | undefined;
  await act(async () => { prompt = assistant.consumePrompt(); });
  expect(prompt).toBe('Abre QR para pagar');

  await act(async () => { assistant.open({ voiceNote: true, channel: 'ia' }); });
  expect(assistant.isOpen).toBe(false);
  expect(assistant.homeSeq).toBe(2);
  await act(async () => tree.unmount());
});

it('Julian, News and direct messages still open in the box over the home', async () => {
  const tree = await mount();
  await act(async () => { assistant.setHomeActive(true); });
  for (const channel of ['julian', 'confio', 'mensajes'] as const) {
    await act(async () => { assistant.open({ channel }); });
    expect(assistant.isOpen).toBe(true);
    await act(async () => { assistant.close(); });
  }
  expect(assistant.openSeq).toBe(3);
  expect(assistant.homeSeq).toBe(0);

  // The box is open over Inicio (Julian's channel) and a request for the
  // assistant arrives: the box steps away so the conversation takes it now.
  await act(async () => { assistant.open({ channel: 'julian' }); });
  expect(assistant.isOpen).toBe(true);
  await act(async () => { assistant.open({ prompt: 'hola' }); });
  expect(assistant.isOpen).toBe(false);
  expect(assistant.homeSeq).toBe(1);

  // Leaving Inicio: requests open the box again.
  await act(async () => { assistant.setHomeActive(false); });
  await act(async () => { assistant.open(); });
  expect(assistant.isOpen).toBe(true);
  await act(async () => tree.unmount());
});
