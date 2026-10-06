// Open/close state for Confio Assistant, the screen the user is on, and the Assistant+ plan.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { navigationRef } from '../navigation/RootNavigation';
import type { AssistantPlan } from './api';
import type { VoiceNote } from './voiceNote';

export type BoxChannel = 'ia' | 'julian' | 'confio';

type OpenOptions = {
  prompt?: string;
  picker?: boolean;
  // Show the server's one-time question ("¿Para qué te gustaría usar Confío?").
  probe?: boolean;
  plus?: boolean;
  call?: boolean;
  channel?: BoxChannel;
  // "Confío" was heard: open on Confio Assistant and start recording a voice note.
  voiceNote?: boolean;
  // Hold-to-talk on the bubble already recorded this note (under accountId):
  // send it, unless the account changed.
  voiceNoteData?: VoiceNote & { accountId?: string };
};

type AssistantState = {
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
  consumeProbe: () => boolean;
  consumePlus: () => boolean;
  consumeCall: () => boolean;
  consumeChannel: () => BoxChannel | undefined;
  consumeVoiceNote: () => boolean;
  consumeVoiceNoteData: () => (VoiceNote & { accountId?: string }) | undefined;
  // Someone (hold-to-talk) owns the microphone: the wake word pauses.
  micBusy: boolean;
  setMicBusy: (busy: boolean) => void;
  // The server answers Confio Assistant (false on older servers: the bubble then
  // opens Mensajes with the classic support thread).
  available: boolean;
  setAvailable: (available: boolean) => void;
  // The support chat is answered by Confio Assistant (false: by people — launch
  // control group or kill switch; the chat itself still works).
  aiEnabled: boolean;
  setAiEnabled: (aiEnabled: boolean) => void;
  plan: AssistantPlan | null;
  setPlan: (plan: AssistantPlan | null) => void;
  // Where the bubble rests, so the open box can grow out of it and point at it.
  bubbleAnchor: { x: number; y: number; size: number } | null;
  setBubbleAnchor: (anchor: { x: number; y: number; size: number } | null) => void;
  // A voice call is live (the wake word pauses, the bubble shows it).
  inCall: boolean;
  setInCall: (inCall: boolean) => void;
  // The chat closed itself to show a screen: the bubble repeats what it said
  // there, so nobody lands on a screen without knowing why.
  navNote: { text: string; seq: number } | null;
  showNavNote: (text: string) => void;
};

const AssistantContext = createContext<AssistantState | null>(null);

export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [route, setRoute] = useState<string | undefined>(() => navigationRef.getCurrentRoute?.()?.name);
  const [request, setRequest] = useState<OpenOptions>({});
  const [available, setAvailable] = useState(false);
  const [aiEnabled, setAiEnabled] = useState(false);
  const [bubbleAnchor, setBubbleAnchor] = useState<{ x: number; y: number; size: number } | null>(null);
  const [plan, setPlan] = useState<AssistantPlan | null>(null);
  const [inCall, setInCall] = useState(false);
  const [micBusy, setMicBusy] = useState(false);
  const [openSeq, setOpenSeq] = useState(0);
  const [navNote, setNavNote] = useState<{ text: string; seq: number } | null>(null);
  const showNavNote = useCallback((text: string) => {
    setNavNote((prev) => ({ text, seq: (prev?.seq ?? 0) + 1 }));
  }, []);

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
  const consumeProbe = useCallback(() => {
    const value = !!request.probe;
    consume('probe');
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
      isOpen, route, open, close, consumePrompt, consumePicker, consumeProbe, consumePlus, consumeCall, consumeChannel,
      consumeVoiceNote, consumeVoiceNoteData, available, setAvailable, aiEnabled, setAiEnabled, plan, setPlan, inCall, setInCall,
      bubbleAnchor, setBubbleAnchor, micBusy, setMicBusy, openSeq, navNote, showNavNote,
    }),
    [isOpen, route, open, close, consumePrompt, consumePicker, consumeProbe, consumePlus, consumeCall, consumeChannel,
      consumeVoiceNote, consumeVoiceNoteData, available,
      aiEnabled, plan, inCall, bubbleAnchor, micBusy, openSeq, navNote, showNavNote],
  );
  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

export function useAssistant() {
  const value = useContext(AssistantContext);
  if (!value) {
    throw new Error('useAssistant must be used inside AssistantProvider');
  }
  return value;
}

// For callers that may render outside the provider (e.g. the inbox before login).
export function useOptionalAssistant() {
  return useContext(AssistantContext);
}
