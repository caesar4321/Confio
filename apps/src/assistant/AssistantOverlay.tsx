// Mounted once above the authenticated navigator: the bubble (every
// screen), its chat, and the background services.
import React from 'react';
import AssistantBubble from './AssistantBubble';
import AssistantGuideCard from './AssistantGuideCard';
import AssistantServices from './AssistantServices';
import AssistantSheet from './AssistantSheet';
import GuidePencil from './GuidePencil';

export default function AssistantOverlay() {
  return (
    <>
      <AssistantServices />
      <AssistantBubble />
      <GuidePencil />
      <AssistantGuideCard />
      <AssistantSheet />
    </>
  );
}
