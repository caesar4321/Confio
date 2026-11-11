/**
 * The payment processor's fee on a local transfer (Infinia), as the server
 * splits it. It is a flat amount per transfer, so it weighs most on small
 * ones: the screens show it on its own line, like the Koywe quotes do.
 */
export type LocalTransferFee = {
  processingUsd: string;
  networkUsd: string;
  maintenanceUsd: string;
  debtUsd: string;
  totalUsd: string;
  deferredUsd: string;
  // Receipts only: the fee left the wallet in a confirmed transaction.
  collected?: boolean | null;
};

export const PROCESSOR_FEE_LABEL = 'Comisión del procesador de pagos';

/** From this share of the amount, the flat fee is worth pointing out. */
export const HEAVY_FEE_SHARE = 0.05;

export type ProcessorFeeView = {
  total: string;
  // Account costs riding on this transfer's fee, named so the total explains itself.
  maintenance: string | null;
  debt: string | null;
  // Part of this transfer's fee it could not cover, carried to a later one.
  deferred: string | null;
  /** Whole percent of the amount the fee takes; null when it is not heavy. */
  heavyPercent: number | null;
};

const positive = (value: string | null | undefined): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
};

/** Null when there is no fee to show (none applies, or the server did not say). */
export function processorFeeView(
  fee: LocalTransferFee | null | undefined,
  amountUsd?: number | string | null,
): ProcessorFeeView | null {
  if (!fee) return null;
  const total = positive(fee.totalUsd);
  if (!total) return null;
  const amount = positive(amountUsd == null ? null : String(amountUsd));
  const share = amount ? total / amount : 0;
  return {
    total: fee.totalUsd,
    maintenance: positive(fee.maintenanceUsd) ? fee.maintenanceUsd : null,
    debt: positive(fee.debtUsd) ? fee.debtUsd : null,
    deferred: positive(fee.deferredUsd) ? fee.deferredUsd : null,
    // Capped: a fee above the amount never sends, and the quote says so itself.
    heavyPercent: share >= HEAVY_FEE_SHARE && share < 1 ? Math.round(share * 100) : null,
  };
}

/** "Incluye US$0.20 de mantenimiento de cuenta." — null when the fee is the transfer's alone. */
export function processorFeeIncludes(view: ProcessorFeeView, formatUsd: (value: string) => string): string | null {
  const parts = [
    view.maintenance ? `${formatUsd(view.maintenance)} de mantenimiento de cuenta` : null,
    view.debt ? `${formatUsd(view.debt)} de comisiones pendientes` : null,
  ].filter(Boolean);
  return parts.length ? `Incluye ${parts.join(' y ')}.` : null;
}

export function processorFeeDeferred(view: ProcessorFeeView, formatUsd: (value: string) => string): string | null {
  return view.deferred ? `Quedan ${formatUsd(view.deferred)} de comisión para tu próxima operación.` : null;
}

/**
 * How a receipt presents the fee. Only a confirmed collection is shown as
 * charged; a transfer that ended without one shows no fee at all rather than
 * a charge that never happened.
 */
export type ReceiptFeeState = 'charged' | 'pending' | 'hidden';

const ENDED_STAGES = new Set(['completed', 'failed', 'refunded']);

export function receiptFeeState(fee: LocalTransferFee | null | undefined, stage: string): ReceiptFeeState {
  if (!processorFeeView(fee)) return 'hidden';
  if (fee!.collected) return 'charged';
  return ENDED_STAGES.has(stage) ? 'hidden' : 'pending';
}

export function heavyFeeNote(view: ProcessorFeeView): string | null {
  return view.heavyPercent == null ? null
    : `La comisión es fija: equivale al ${view.heavyPercent}% de este envío. En montos mayores pesa menos.`;
}
