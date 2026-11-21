// The one signing flow every Cuenta inteligente action goes through:
//
//   prepare (server builds the exact batch)  ->  confirm (the server's own
//   summary lines)  ->  sign with the personal key and relay  ->  outcome
//
// Outcomes are kept apart on purpose. "unknown" means the batch may have
// been broadcast and the verdict never reached this phone: it is shown as
// "we are confirming", never as a failure, and never offers a blind retry
// (the same rule as the send and trade flows).
import { useCallback, useEffect, useRef, useState } from 'react';
import { ensureFaceCheck, FACE_STEP_UP_MESSAGE } from '../../services/faceStepUp';
import {
  signAndSubmitPrepared,
  type SmartAccountPreparedBatch,
  type SmartSubmitOutcome,
} from '../../services/smartAccount';

export type SignPhase =
  | 'idle'
  | 'preparing'
  | 'confirm'
  | 'signing'
  | 'executed'
  | 'unknown'
  | 'failed';

export interface SignFlowState {
  phase: SignPhase;
  /** Verbatim server summary of what is about to be signed. */
  summary: string[];
  /** User-facing reason when phase is 'failed'. */
  error: string;
  /** Multi-batch moves: which signature this is (1-based) and how many. */
  step: number;
  steps: number;
  txHash: string | null;
  /** The server's code when phase is 'failed' and it gave one (null otherwise). */
  errorCode: string | null;
}

export interface SignFlowRequest {
  /** Builds batch `index` (0-based). Called again for each further batch. */
  prepare: (index: number) => Promise<SmartAccountPreparedBatch>;
  /** How many batches (signatures) the action takes. Default 1. */
  batches?: number;
  /**
   * The server rebuilds the batch list from live balances on every prepare,
   * so after a batch executes the old index 1 may now be index 0. With this
   * set, every further batch is requested as index 0 again until the server
   * says there is nothing left (`nothing_to_move`) or the expected count is
   * reached. The loop is bounded by `batches`, so it can never run away.
   */
  repeatFirst?: boolean;
  /** Sign straight away, without the confirm step (the claim-cancel alert). */
  skipConfirm?: boolean;
  /**
   * The action hands money (or a path to it) to someone else, so the server
   * asks for Confío Face: a send rule, a bank payment rule, naming a
   * beneficiary or changing their window. Exactly the personal send's
   * mechanism (bscSend.ts): on `face_required` from the prepare, show
   * Confío Face and prepare once more; on the sponsor's Face refusal at
   * submit, show it and submit the same batch once more. A cancelled or
   * failed check signs nothing and shows the send flow's own sentence.
   */
  faceStepUp?: boolean;
}

/** The server's prepare code when no fresh Confío Face grant exists. */
export const FACE_REQUIRED_CODE = 'face_required';

/** The outgoing-identity restriction also arrives as `face_required` (the
 *  server's require_outgoing_face raises it): Face cannot lift it. */
const IDENTITY_RESTRICTION_TEXT = 'Las salidas de tu cuenta están temporalmente restringidas';

/** Show Confío Face for a money movement; true only when the server passed it. */
async function faceCheckPassed(): Promise<boolean> {
  try {
    return await ensureFaceCheck('withdrawal');
  } catch {
    return false;
  }
}

/** Server answers to a further prepare that mean "the earlier ones covered it". */
const DONE_CODES = new Set(['nothing_to_move', 'bad_batch_index']);

const IDLE: SignFlowState = { phase: 'idle', summary: [], error: '', step: 1, steps: 1, txHash: null, errorCode: null };

const NOT_SENT_COPY: Record<string, string> = {
  signing_window_closed: 'La operación venció antes de firmarse. No se movió nada. Inténtalo de nuevo.',
  sponsored_rail_unavailable: 'Este servicio no está disponible en este momento. No se movió nada.',
  empty_batch: 'No hay nada que firmar. No se movió nada.',
  malformed_batch: 'No pudimos leer la operación, así que no la firmamos. No se movió nada.',
};

/**
 * Policy refusals from the sponsor (cusd_plus/schema.py SponsorBscBatch,
 * smart_account/relay_policy.py) and the prepare codes they share
 * (smart_account/services.py MESSAGES, server wording reused). Retrying the
 * same thing would only be refused again, so none says "Inténtalo de nuevo":
 * each says what to do instead. The generic retry copy is kept for transport
 * and unknown errors only.
 */
export const POLICY_COPY: Record<string, string> = {
  identity_restricted: 'Las salidas de tu cuenta están temporalmente restringidas. Contacta con soporte para revisar tu cuenta. No se movió nada.',
  identity_hold: 'Tu cuenta está en revisión. Escríbenos por soporte para continuar. No se movió nada.',
  payment_due: 'Tu Cuenta inteligente tiene un pago pendiente. Agrega dólares para continuar. No se movió nada.',
  account_not_active: 'Tu Cuenta inteligente no está activa. No se movió nada.',
  smart_account_not_registered: 'Tu Cuenta inteligente todavía no está lista. No se movió nada.',
  smart_action_expired: 'La operación venció antes de enviarse. No se movió nada. Vuelve a prepararla para ver los datos actuales.',
  smart_action_consumed: 'Esta operación ya se había enviado, así que no la enviamos otra vez. Revisa tus movimientos.',
  smart_action_not_prepared: 'La operación ya no coincide con la que preparamos. No se movió nada. Vuelve a prepararla.',
  smart_action_mismatch: 'La operación ya no coincide con la que preparamos. No se movió nada. Vuelve a prepararla.',
  claim_cancel_required: 'Tu beneficiario pidió tu cuenta mientras firmabas. No se movió nada. Vuelve a preparar la operación: al firmarla, su pedido se cancela.',
  claim_cancel_not_allowed: 'No pudimos cancelar el pedido de tu beneficiario con esta operación. No se movió nada.',
  recipient_is_smart_account: 'Esa dirección es una Cuenta inteligente. Para agregar dólares, usa "Agregar" dentro de la Cuenta inteligente; no se puede enviar a ella desde aquí.',
  complex_product_ack_required: 'Para comprar fondos apalancados o inversos, actualiza la app y confirma que entiendes cómo funcionan. No se movió nada.',
  crypto_ack_required: 'Acepta primero los riesgos de bitcoin y oro en Invertir. No se movió nada.',
  trade_not_available: 'Esta inversión no está disponible para tu cuenta. No se movió nada.',
  review_amount_cap: 'Ese monto supera el límite de tu cuenta. Prueba con un monto menor. No se movió nada.',
  insufficient_balance: 'No tienes saldo suficiente. No se movió nada.',
  no_own_account: 'Necesitas tu propia Cuenta inteligente activa para mover los activos allí. No se movió nada.',
  beneficiary_residence_unknown: 'No pudimos confirmar el país de residencia de esa persona. Debe completar su perfil en Confío antes de ser nombrada.',
  beneficiary_ineligible: 'Por su país de residencia, esa persona no puede ser beneficiaria.',
  beneficiary_unverified: 'Tu beneficiario debe verificar su identidad en Confío antes de ser nombrado.',
  beneficiary_on_hold: 'Esa persona no puede ser nombrada beneficiaria en este momento.',
  destination_not_allowed: 'Ese destino no está permitido para esta operación. No se movió nada.',
  withdraw_destination_not_allowed: 'Solo puedes mover lo que tiene a tu propia billetera. No se movió nada.',
  disabled: 'La Cuenta inteligente todavía no está disponible. No se movió nada.',
  // A decline (BeneficiaryInviteScreen) that races this person's own acceptance.
  designation_acceptance_in_progress: 'Ya empezaste a aceptar esta designación. Si no llegaste a firmarla, podrás rechazarla en una hora.',
  designation_already_accepted: 'Ya aceptaste esta designación, así que no se puede rechazar.',
  // Transient (the quote is being refreshed), so waiting and retrying is the answer.
  stock_quote_window: 'El precio cambió mientras preparábamos la operación. Vuelve a intentarlo en un minuto.',
  // Only after the Confío Face step-up did not pass: the send flow's own sentence.
  face_required: FACE_STEP_UP_MESSAGE,
};

/** A later step failed: the earlier ones DID move, so never say "nada". */
export function laterStepFailedMessage(base: string, step: number, steps: number): string {
  const trimmed = base.replace(/\s*No se movió nada\.?/g, '').replace(/\s*Puedes intentarlo de nuevo\.?|\s*Inténtalo de nuevo\.?/g, '').trim();
  const of = steps > 1 ? ` (firma ${step} de ${steps})` : '';
  return `${trimmed} Los pasos anteriores sí se completaron; este${of} no se realizó.`.trim();
}

/** Copy for a batch that definitely did not go through. */
export function notSentMessage(outcome: Extract<SmartSubmitOutcome, { status: 'not_sent' | 'reverted' }>): string {
  if (outcome.status === 'reverted') {
    return 'La red no aceptó la operación. No se movió nada. Puedes intentarlo de nuevo.';
  }
  return NOT_SENT_COPY[outcome.code]
    ?? POLICY_COPY[outcome.code]
    ?? 'No pudimos completar la operación. No se movió nada. Inténtalo de nuevo.';
}

export function useSignFlow(options: { onExecuted?: () => void } = {}) {
  const [state, setState] = useState<SignFlowState>(IDLE);
  const request = useRef<SignFlowRequest | null>(null);
  const prepared = useRef<SmartAccountPreparedBatch | null>(null);
  // Refs, not state: two taps in the same frame must still sign once.
  const busy = useRef(false);
  const mounted = useRef(true);
  const onExecuted = useRef(options.onExecuted);
  onExecuted.current = options.onExecuted;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const set = useCallback((next: Omit<SignFlowState, 'errorCode'> & { errorCode?: string | null }) => {
    if (mounted.current) {
      setState({ ...next, errorCode: next.errorCode ?? null });
    }
  }, []);

  const runFrom = useCallback(async (index: number, first: SmartAccountPreparedBatch) => {
    const req = request.current;
    if (!req) {
      return;
    }
    const steps = Math.max(1, req.batches ?? 1);
    let batch: SmartAccountPreparedBatch = first;
    let lastHash: string | null = null;
    let executed = 0;
    // The submit-time Face refusal is answered once per flow, never in a loop.
    let faceRetried = false;
    // True only while signAndSubmitPrepared runs: a throw there may mean the
    // batch was broadcast, so it is "unknown", never "failed".
    let submitting = false;
    let i = index;
    try {
      for (; i < steps; i++) {
        if (i > index) {
          set({ phase: 'signing', summary: [], error: '', step: i + 1, steps, txHash: lastHash });
          batch = await req.prepare(req.repeatFirst ? 0 : i);
          if (!batch.success) {
            if (executed > 0 && batch.errorCode && DONE_CODES.has(batch.errorCode)) {
              // The earlier batches already moved everything there was.
              break;
            }
            // Earlier batches already moved; say exactly that.
            set({
              phase: 'failed',
              summary: [],
              error: laterStepFailedMessage(
                batch.errorMessage || (batch.errorCode && POLICY_COPY[batch.errorCode]) || 'No pudimos preparar el siguiente paso.',
                i + 1, steps,
              ),
              step: i + 1,
              steps,
              txHash: lastHash,
              errorCode: batch.errorCode ?? null,
            });
            return;
          }
        }
        set({ phase: 'signing', summary: batch.summary ?? [], error: '', step: i + 1, steps, txHash: lastHash });
        submitting = true;
        let outcome = await signAndSubmitPrepared(batch);
        submitting = false;
        if (req.faceStepUp && !faceRetried && outcome.status === 'not_sent' && outcome.code === FACE_REQUIRED_CODE) {
          // The Face window lapsed between prepare and submit (the sponsor
          // refused before any broadcast): confirm again, then the same batch.
          faceRetried = true;
          if (!(await faceCheckPassed())) {
            set({
              phase: 'failed', summary: [],
              error: executed > 0 ? laterStepFailedMessage(FACE_STEP_UP_MESSAGE, i + 1, steps) : FACE_STEP_UP_MESSAGE,
              step: i + 1, steps, txHash: lastHash, errorCode: FACE_REQUIRED_CODE,
            });
            return;
          }
          set({ phase: 'signing', summary: batch.summary ?? [], error: '', step: i + 1, steps, txHash: lastHash });
          submitting = true;
          outcome = await signAndSubmitPrepared(batch);
          submitting = false;
        }
        if (outcome.status === 'unknown') {
          set({ phase: 'unknown', summary: [], error: '', step: i + 1, steps, txHash: outcome.txHash });
          return;
        }
        if (outcome.status !== 'executed') {
          set({
            phase: 'failed', summary: [],
            error: executed > 0 ? laterStepFailedMessage(notSentMessage(outcome), i + 1, steps) : notSentMessage(outcome),
            step: i + 1, steps, txHash: lastHash,
            errorCode: outcome.status === 'not_sent' ? outcome.code : null,
          });
          return;
        }
        executed += 1;
        lastHash = outcome.txHash;
      }
    } catch {
      if (submitting) {
        set({ phase: 'unknown', summary: [], error: '', step: i + 1, steps, txHash: lastHash });
      } else {
        set({
          phase: 'failed', summary: [],
          error: executed > 0
            ? laterStepFailedMessage('No pudimos preparar el siguiente paso.', i + 1, steps)
            : 'No pudimos completar la operación. No se movió nada. Inténtalo de nuevo.',
          step: i + 1, steps, txHash: lastHash,
        });
      }
      return;
    }
    set({ phase: 'executed', summary: [], error: '', step: steps, steps, txHash: lastHash });
    onExecuted.current?.();
  }, [set]);

  /** Ask the server for the batch and show what will be signed. */
  const start = useCallback(async (req: SignFlowRequest) => {
    if (busy.current) {
      return;
    }
    busy.current = true;
    request.current = req;
    prepared.current = null;
    const steps = Math.max(1, req.batches ?? 1);
    set({ ...IDLE, phase: 'preparing', steps });
    try {
      let batch = await req.prepare(0);
      if (
        req.faceStepUp && !batch.success && batch.errorCode === FACE_REQUIRED_CODE
        && !(batch.errorMessage || '').startsWith(IDENTITY_RESTRICTION_TEXT)
      ) {
        // The personal send's step-up: Confío Face, then the same prepare
        // once more. A second `face_required` is shown, never looped on.
        if (!(await faceCheckPassed())) {
          set({ ...IDLE, phase: 'failed', steps, error: FACE_STEP_UP_MESSAGE, errorCode: FACE_REQUIRED_CODE });
          return;
        }
        batch = await req.prepare(0);
      }
      if (!batch.success) {
        set({
          ...IDLE, phase: 'failed', steps,
          error: batch.errorMessage
            || (batch.errorCode && POLICY_COPY[batch.errorCode])
            || 'No pudimos preparar la operación. Inténtalo de nuevo.',
          errorCode: batch.errorCode ?? null,
        });
        return;
      }
      prepared.current = batch;
      if (req.skipConfirm) {
        await runFrom(0, batch);
        return;
      }
      set({ ...IDLE, phase: 'confirm', summary: batch.summary ?? [], steps });
    } catch {
      // Nothing was signed: preparing threw (no connection, bad answer).
      set({ ...IDLE, phase: 'failed', steps, error: 'No pudimos preparar la operación. No se movió nada. Inténtalo de nuevo.' });
    } finally {
      busy.current = false;
    }
  }, [runFrom, set]);

  /** The user accepted the summary: sign and relay. */
  const confirm = useCallback(async () => {
    const batch = prepared.current;
    if (busy.current || !batch) {
      return;
    }
    busy.current = true;
    prepared.current = null; // a prepared batch is signed at most once
    try {
      await runFrom(0, batch);
    } catch {
      // runFrom settles every path itself; this is the last guard so the
      // sheet never stays on 'signing'. The verdict was not seen.
      set({ ...IDLE, phase: 'unknown', steps: Math.max(1, request.current?.batches ?? 1) });
    } finally {
      busy.current = false;
    }
  }, [runFrom, set]);

  const reset = useCallback(() => {
    if (busy.current) {
      return;
    }
    request.current = null;
    prepared.current = null;
    set(IDLE);
  }, [set]);

  return { state, start, confirm, reset };
}

export type SignFlow = ReturnType<typeof useSignFlow>;
