import type { PhoneRelinkConfirmation } from './phoneRelinkConfirmation';

export type PhoneVerificationResult = {
  success?: boolean;
  error?: string;
  retryable?: boolean;
  relinkConfirmation?: PhoneRelinkConfirmation | null;
};

type Dependencies = {
  verify: () => Promise<PhoneVerificationResult | null | undefined>;
  confirm: (token: string) => Promise<PhoneVerificationResult | null | undefined>;
  ask: (confirmation: PhoneRelinkConfirmation) => Promise<boolean>;
  retry: (confirmation: PhoneRelinkConfirmation) => Promise<boolean>;
  isActive: () => boolean;
  reset: () => void;
};

// Keep provider-approved proof between button presses: the OTP may already be
// consumed even though confirmation has not committed (or its response was lost).
export function createPhoneRelinkFlow() {
  let pending: { confirmation: PhoneRelinkConfirmation; approved: boolean } | null = null;
  return {
    clear() { pending = null; },
    async run(deps: Dependencies): Promise<PhoneVerificationResult | null> {
      if (!pending) {
        const verified = await deps.verify();
        if (!deps.isActive()) return null;
        if (!verified?.relinkConfirmation) return verified || null;
        pending = { confirmation: verified.relinkConfirmation, approved: false };
      }
      while (pending && deps.isActive()) {
        if (!pending.approved) {
          const approved = await deps.ask(pending.confirmation);
          if (!deps.isActive()) return null;
          if (!approved) {
            pending = null;
            deps.reset();
            return null;
          }
          pending.approved = true;
        }
        const { confirmation } = pending;
        let result: PhoneVerificationResult | null | undefined;
        try {
          result = await deps.confirm(confirmation.token);
        } catch {
          if (!deps.isActive()) return null;
          const retrying = await deps.retry(confirmation);
          if (!deps.isActive()) return null;
          if (!retrying) {
            // Keep the token (the OTP may already be consumed) but not the consent:
            // after declining, the next attempt must be approved again.
            if (pending) pending.approved = false;
            return null;
          }
          continue;
        }
        if (!deps.isActive()) return null;
        if (result?.relinkConfirmation) {
          pending = { confirmation: result.relinkConfirmation, approved: false };
          continue;
        }
        if (!result) {
          // A missing mutation payload is also an uncertain outcome.
          return { success: false, retryable: true, error: 'No pudimos confirmar el cambio. Intenta de nuevo.' };
        }
        if (!result.retryable || result.success) {
          pending = null;
          if (!result.success) deps.reset();
        }
        return result;
      }
      return null;
    },
  };
}
