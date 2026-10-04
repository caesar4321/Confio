// Mounted once above the authenticated navigator: the bubble (every
// screen), its chat, and the background services.
import React from 'react';
import AssistantBubble from './AssistantBubble';
import AssistantServices from './AssistantServices';
import AssistantSheet from './AssistantSheet';

export default function AssistantOverlay() {
  return (
    <>
      <AssistantServices />
      <AssistantBubble />
      <AssistantSheet />
    </>
  );
}
