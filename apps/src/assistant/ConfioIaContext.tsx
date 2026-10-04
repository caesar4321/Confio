// Open/close state for Confío IA, the screen the user is on, and the IA+ plan.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { navigationRef } from '../navigation/RootNavigation';
import type { ConfioIaPlan } from './api';
import type { VoiceNote } from './voiceNote';

export type BoxChannel = 'ia' | 'julian' | 'confio';

type OpenOptions = {
  prompt?: string;
  picker?: boolean;
  plus?: boolean;
  call?: boolean;
  channel?: BoxChannel;
  // "Confío" was heard: open on Confío IA and start recording a voice note.
  voiceNote?: boolean;
  // Hold-to-talk on the bubble already recorded this note (under accountId):
  // send it, unless the account changed.
  voiceNoteData?: VoiceNote & { accountId?: string };
};

type ConfioIaState = {
  isOpen: boolean;
  route?: string;
  open: (opts?: OpenOptions) => void;
  // Bumped by every open(), also while already open (e.g. a notification
  // asking for another channel): the sheet re-reads the request on change.
  openSeq: number;
  close: () => void;
  // One-shot requests the sheet consumes when it opens.
  consumePrompt: () => string | undefined;
  consumePicker: () => boolean;
  consumePlus: () => boolean;
  consumeCall: () => boolean;
  consumeChannel: () => BoxChannel | undefined;
  consumeVoiceNote: () => boolean;
  consumeVoiceNoteData: () => (VoiceNote & { accountId?: string }) | undefined;
  // Someone (hold-to-talk) owns the microphone: the wake word pauses.
  micBusy: boolean;
  setMicBusy: (busy: boolean) => void;
  // The server answers Confío IA (false on older servers: the bubble then
  // opens Mensajes with the classic support thread).
  available: boolean;
  setAvailable: (available: boolean) => void;
  // The support chat is answered by Confío IA (false: by people — launch
  // control group or kill switch; the chat itself still works).
  aiEnabled: boolean;
  setAiEnabled: (aiEnabled: boolean) => void;
  plan: ConfioIaPlan | null;
  setPlan: (plan: ConfioIaPlan | null) => void;
  // Where the bubble rests, so the open box can grow out of it and point at it.
  bubbleAnchor: { x: number; y: number; size: number } | null;
  setBubbleAnchor: (anchor: { x: number; y: number; size: number } | null) => void;
  // A voice call is live (the wake word pauses, the bubble shows it).
  inCall: boolean;
  setInCall: (inCall: boolean) => void;
};

const ConfioIaContext = createContext<ConfioIaState | null>(null);

export function ConfioIaProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [route, setRoute] = useState<string | undefined>(() => navigationRef.getCurrentRoute?.()?.name);
  const [request, setRequest] = useState<OpenOptions>({});
  const [available, setAvailable] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(false);
  const [bubbleAnchor, setBubbleAnchor] = useState<{ x: number; y: number; size: number } | null>(null);
  const [plan, setPlan] = useState<ConfioIaPlan | null>(null);
  const [inCall, setInCall] = useState(false);
  const [micBusy, setMicBusy] = useState(false);
  const [openSeq, setOpenSeq] = useState(0);

  useEffect(() => {
    const update = () => setRoute(navigationRef.getCurrentRoute?.()?.name);
    update();
    return navigationRef.addListener('state', update);
  }, []);

  const open = useCallback((opts: OpenOptions = {}) => {
    setRequest(opts);
    setOpenSeq((n) => n + 1);
    setIsOpen(true);
  }, []);
  const close = useCallback(() => setIsOpen(false), []);

  const consume = useCallback(<K extends keyof OpenOptions>(key: K): OpenOptions[K] => {
    let value: OpenOptions[K] | undefined;
    setRequest((prev) => {
      value = prev[key];
      if (value === undefined) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
    return value as OpenOptions[K];
  }, []);

  // Reads happen in the effect right after opening, from the latest state.
  const consumePrompt = useCallback(() => {
    const value = request.prompt;
    consume('prompt');
    return value;
  }, [request, consume]);
  const consumePicker = useCallback(() => {
    const value = !!request.picker;
    consume('picker');
    return value;
  }, [request, consume]);
  const consumePlus = useCallback(() => {
    const value = !!request.plus;
    consume('plus');
    return value;
  }, [request, consume]);
  const consumeCall = useCallback(() => {
    const value = !!request.call;
    consume('call');
    return value;
  }, [request, consume]);
  const consumeChannel = useCallback(() => {
    const value = request.channel;
    consume('channel');
    return value;
  }, [request, consume]);
  const consumeVoiceNote = useCallback(() => {
    const value = !!request.voiceNote;
    consume('voiceNote');
    return value;
  }, [request, consume]);
  const consumeVoiceNoteData = useCallback(() => {
    const value = request.voiceNoteData;
    consume('voiceNoteData');
    return value;
  }, [request, consume]);

  const value = useMemo(
    () => ({
      isOpen, route, open, close, consumePrompt, consumePicker, consumePlus, consumeCall, consumeChannel,
      consumeVoiceNote, consumeVoiceNoteData, available, setAvailable, aiEnabled, setAiEnabled, plan, setPlan, inCall, setInCall,
      bubbleAnchor, setBubbleAnchor, micBusy, setMicBusy, openSeq,
    }),
    [isOpen, route, open, close, consumePrompt, consumePicker, consumePlus, consumeCall, consumeChannel,
      consumeVoiceNote, consumeVoiceNoteData, available,
      aiEnabled, plan, inCall, bubbleAnchor, micBusy, openSeq],
  );
  return <ConfioIaContext.Provider value={value}>{children}</ConfioIaContext.Provider>;
}

export function useConfioIa() {
  const value = useContext(ConfioIaContext);
  if (!value) {
    throw new Error('useConfioIa must be used inside ConfioIaProvider');
  }
  return value;
}

// For callers that may render outside the provider (e.g. the inbox before login).
export function useOptionalConfioIa() {
  return useContext(ConfioIaContext);
}
