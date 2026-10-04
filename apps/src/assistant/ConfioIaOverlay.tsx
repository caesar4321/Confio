// Mounted once above the authenticated navigator: the bubble (every
// screen), its chat, and the background services.
import React from 'react';
import ConfioIaBubble from './ConfioIaBubble';
import ConfioIaServices from './ConfioIaServices';
import ConfioIaSheet from './ConfioIaSheet';

export default function ConfioIaOverlay() {
  return (
    <>
      <ConfioIaServices />
      <ConfioIaBubble />
      <ConfioIaSheet />
    </>
  );
}
