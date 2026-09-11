import { useEffect, useRef, useState } from 'react';
import type { PhoneRelinkConfirmation } from '../utils/phoneRelinkConfirmation';

export type PhoneRelinkPromptPhase = 'ask' | 'confirming' | 'retry';

export type PhoneRelinkPrompt = {
  id: number;
  confirmation: PhoneRelinkConfirmation;
  phase: PhoneRelinkPromptPhase;
  /** The accounts changed after the user had already approved an earlier prompt. */
  replaced: boolean;
};

/**
 * Bridges the promise-based relink flow to PhoneRelinkModal.
 *
 * The modal stays presented from the first question until the caller closes it
 * once the flow settles, so a replacement confirmation or a retry swaps content
 * in place instead of re-presenting a native modal that may still be
 * dismissing (iOS drops that presentation and the flow would wait forever).
 * Every answer is bound to the id of the prompt it was rendered for, so a stale
 * callback can never approve accounts the user has not seen.
 */
export function usePhoneRelinkPrompt() {
  const [prompt, setPrompt] = useState<PhoneRelinkPrompt | null>(null);
  const shown = useRef<PhoneRelinkPrompt | null>(null);
  const pending = useRef<{ id: number; resolve: (approved: boolean) => void } | null>(null);
  const lastId = useRef(0);

  const show = (next: PhoneRelinkPrompt | null) => {
    shown.current = next;
    setPrompt(next);
  };

  const settle = (approved: boolean) => {
    const question = pending.current;
    pending.current = null;
    question?.resolve(approved);
  };

  const waitFor = (confirmation: PhoneRelinkConfirmation, phase: 'ask' | 'retry') =>
    new Promise<boolean>(resolve => {
      settle(false); // only one question is ever open; an older one fails closed
      const id = ++lastId.current;
      pending.current = { id, resolve };
      show({ id, confirmation, phase, replaced: phase === 'ask' && shown.current !== null });
    });

  useEffect(() => () => {
    const question = pending.current;
    pending.current = null;
    question?.resolve(false);
  }, []);

  return {
    prompt,
    ask: (confirmation: PhoneRelinkConfirmation) => waitFor(confirmation, 'ask'),
    retry: (confirmation: PhoneRelinkConfirmation) => waitFor(confirmation, 'retry'),
    answer: (id: number, approved: boolean) => {
      // Stale: that prompt was already answered or has been replaced.
      if (pending.current?.id !== id) return;
      show(approved && shown.current ? { ...shown.current, phase: 'confirming' } : null);
      settle(approved);
    },
    close: () => {
      settle(false);
      show(null);
    },
  };
}
