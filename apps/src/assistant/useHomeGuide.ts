// The first-steps guide inside the home conversation
// (docs/designs/ai-assistant-first-redesign.md 7.5). The server still decides
// the step (verify, top up, first action…) and its wording; here it is the
// assistant's newest message with its chips, instead of a card over the tabs.
// A chip that leads somewhere hands its trail to the walk engine
// (AssistantGuideCard), which opens the screen and points inside it.
//
// Life of a step here:
// - It is drawn as soon as the server names it, and counts as "shown" once
//   Inicio has been looked at for a moment (once per day at most).
// - A tap decides it: a chip accepts it (and walks, or brings the next
//   step), "Ahora no" refuses it.
// - Writing instead of tapping decides nothing: the first answer keeps to the
//   step and its chips stay under that reply; with the next message the
//   conversation has moved on and the step leaves for the day.
// - When the server names a different step (the person did this one some
//   other way, a verification came back), the new one replaces it.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client';
import {
  GET_ASSISTANT_GUIDE,
  RECORD_ASSISTANT_GUIDE_EVENT,
  type AssistantGuide,
  type AssistantGuideChip,
} from './api';
import { requestGuideTrail, subscribeGuideRefresh } from './guidePointer';
import { GUIDE_TOP_UP_STEP, requestTopUpDecline } from './guideTopUpDecline';
import { sawTopUpPriceThisRun } from '../services/topUpExit';

const HOME_ROUTE = 'Home';
const NEXT_STEP_LIMIT_MS = 8000;
// A screen crossed on the way elsewhere is not a step someone was shown.
const SHOWN_AFTER_MS = 800;
// The funnel's `detail` on "shown": tells these from the old card's.
const SURFACE = 'conversation';
// Chips of a kind this build does not know are not drawn.
// pet: opens the pet's picker; skip: no, and the next step now; ask: the
// chip's words go as the person's own question (the conversation sends it).
const CHIP_KINDS = new Set(['navigate', 'probe', 'dismiss', 'pet', 'skip', 'ask']);

// A stuck network must never leave the waiting dots on screen for good.
function withinLimit<T>(work: Promise<T>): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([
    work,
    new Promise<null>((resolve) => {
      timer = setTimeout(() => resolve(null), NEXT_STEP_LIMIT_MS);
    }),
  ]).finally(() => clearTimeout(timer));
}

const today = () => new Date().toDateString();

export type HomeGuide = {
  /** The step to say now, with only the chips this build can act on. Null
   * whenever the conversation is not the place for it (see `enabled`). */
  guide: AssistantGuide | null;
  /** The server has said whether there is a step (or the read failed): until
   * then an empty thread must not greet, or the greeting would be swapped
   * for the step a moment later. Always true when not `enabled`. */
  settled: boolean;
  /** The person already wrote back about this step: its sentence has been
   * answered, so only its chips stay, under the reply. */
  replied: boolean;
  /** An answer was tapped and the next step is on its way. */
  pending: boolean;
  press: (chip: AssistantGuideChip) => void;
  /** The person is sending a message. The first one after a step keeps to it
   * (the returned `step` goes with the question, `finish` once it is
   * answered); a later one means the conversation moved on, and the step
   * leaves. Null when there is nothing to keep to. */
  beginReply: () => { step: string; finish: (answered: boolean) => void } | null;
};

export function useHomeGuide(enabled: boolean, contextKey: string): HomeGuide {
  const [guide, setGuide] = useState<AssistantGuide | null>(null);
  const [pending, setPending] = useState(false);
  const [replied, setReplied] = useState(false);
  // Two different things, kept apart: a step whose "shown" was recorded may
  // be drawn again (verify → verifying → verify), but is not counted again;
  // a step the person left (a tap, or a second message) is not drawn again.
  // Both are for the day: the app can stay alive far longer than that.
  const day = useRef(today());
  const counted = useRef(new Set<string>());
  const left = useRef(new Set<string>());
  const sets = useCallback(() => {
    if (day.current !== today()) {
      day.current = today();
      counted.current = new Set();
      left.current = new Set();
    }
    return { counted: counted.current, left: left.current };
  }, []);
  const flow = useRef(0);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const { data, loading, refetch } = useQuery(GET_ASSISTANT_GUIDE, {
    variables: { screen: HOME_ROUTE, contextKey },
    skip: !enabled,
    fetchPolicy: 'network-only',
    errorPolicy: 'ignore',
  });
  const [recordEvent] = useMutation(RECORD_ASSISTANT_GUIDE_EVENT, { errorPolicy: 'ignore' });
  const record = useCallback((step: string, event: string, answer?: string, detail?: string) => (
    recordEvent({ variables: { step, event, answer, detail } }).catch(() => undefined)
  ), [recordEvent]);

  // Something changed elsewhere (an identity came back approved).
  useEffect(() => subscribeGuideRefresh(() => {
    if (enabledRef.current) {
      refetch().catch(() => undefined);
    }
  }), [refetch]);

  const show = useCallback((next: AssistantGuide) => {
    setReplied(false);
    setGuide({ ...next, chips: next.chips.filter((c) => CHIP_KINDS.has(c.kind)) });
  }, []);

  // The server names a step: say it, unless the person already left it
  // today. A different step than the one on screen replaces it (the person
  // topped up from the menu: "Ya puedes recargar" must not stay). No step
  // named changes nothing: a step that was just counted as shown rests on
  // the server, and that silence must not take it off the screen.
  const current = guide?.step;
  useEffect(() => {
    const next: AssistantGuide | null | undefined = data?.assistantGuide;
    if (!enabled || pending || !next || next.step === current || sets().left.has(next.step)) {
      return;
    }
    show(next);
  }, [data, enabled, pending, current, show, sets]);

  // Looked at for a moment: now it counts as shown, once.
  useEffect(() => {
    if (!enabled || !current || sets().counted.has(current)) {
      return undefined;
    }
    const timer = setTimeout(() => {
      sets().counted.add(current);
      record(current, 'shown', undefined, SURFACE);
    }, SHOWN_AFTER_MS);
    return () => clearTimeout(timer);
  }, [enabled, current, record, sets]);

  // A guide belongs to one personal account: never carried across a switch.
  useEffect(() => () => {
    flow.current += 1;
    setGuide(null);
    setPending(false);
    setReplied(false);
  }, [contextKey]);

  const nextStep = useCallback(async (run: number, work: Promise<unknown>) => {
    const next = await withinLimit((async () => {
      await work;
      const result = await refetch().catch(() => null);
      return result?.data?.assistantGuide as AssistantGuide | null | undefined;
    })());
    if (run !== flow.current) {
      return; // another account, or something else took over meanwhile
    }
    setPending(false);
    // The same step again means the answer did not reach the server: it
    // comes back to be answered, instead of vanishing with the answer lost.
    if (next && !sets().left.has(next.step) && enabledRef.current) {
      show(next);
    }
  }, [refetch, show, sets]);

  const press = useCallback((chip: AssistantGuideChip) => {
    const step = guide;
    if (!step || pending || !enabledRef.current) {
      return;
    }
    if (chip.kind === 'ask') {
      // A question, not an answer to the step: it stays, as when they type one.
      return;
    }
    flow.current += 1;
    // Tapped before the moment was up: it was seen all the same.
    if (!sets().counted.has(step.step)) {
      sets().counted.add(step.step);
      record(step.step, 'shown', undefined, SURFACE);
    }
    setGuide(null);
    if (chip.kind === 'probe' || chip.kind === 'pet') {
      // Not "left" yet: only once the server has moved on to the next step.
      setPending(true);
      void nextStep(flow.current, record(step.step, 'accepted', chip.answer));
      return;
    }
    if (chip.kind === 'skip') {
      // Settled with a no, and on to what comes next right away.
      setPending(true);
      void nextStep(flow.current, record(step.step, 'dismissed'));
      return;
    }
    sets().left.add(step.step);
    if (chip.kind === 'dismiss') {
      record(step.step, 'dismissed');
      // Said no to topping up before seeing any price: one tap asks why.
      if (step.step === GUIDE_TOP_UP_STEP && !sawTopUpPriceThisRun()) {
        requestTopUpDecline();
      }
      return;
    }
    record(step.step, 'accepted', undefined, chip.answer);
    requestGuideTrail({ step: step.step, detail: chip.answer, stops: chip.trail });
  }, [guide, pending, record, nextStep, sets]);

  const beginReply = useCallback(() => {
    const step = guide;
    if (!step || !enabledRef.current) {
      return null;
    }
    if (replied) {
      // A second message: the conversation moved on. Chips left under an
      // answer about something else would be a question nobody asked. Not
      // recorded as refused: the step is free to come back another day.
      flow.current += 1;
      sets().left.add(step.step);
      setGuide(null);
      return null;
    }
    const run = flow.current;
    return {
      step: step.step,
      finish: (answered: boolean) => {
        // Not answered (a failed send): the step stays as it was.
        if (!answered || run !== flow.current) {
          return;
        }
        // Whatever they wrote, a "hola" included, decides nothing: the chips
        // stay under the reply. Only a tap accepts or refuses a step.
        setReplied(true);
        record(step.step, 'replied');
      },
    };
  }, [guide, replied, record, sets]);

  // Not the place for it right now (the team has the thread, another screen
  // is in front): nothing is drawn, and the step waits.
  return {
    guide: enabled ? guide : null,
    // Errors are ignored by this read: "not loading" is the answer either way.
    settled: !enabled || data !== undefined || !loading,
    replied,
    pending: enabled && pending,
    press,
    beginReply,
  };
}
