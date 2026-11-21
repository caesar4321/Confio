// Test fixtures and helpers for the Cuenta inteligente screens. Not imported
// by app code. Values are shaped exactly like the frozen GraphQL contract.
import type renderer from 'react-test-renderer';
import { act } from 'react-test-renderer';
import type {
  BeneficiaryDesignation, InheritedAccount, SmartAccount, SmartAccountBeneficiary, SmartAccountMovePreview,
  SmartAccountOffer, SmartAccountPreparedBatch, SmartAccountRule,
} from '../../../services/smartAccount';

export const ok = <T,>(data: T) => ({ ok: true as const, data });
export const failedRead = { ok: false as const };

export const offer = (over: Partial<SmartAccountOffer> = {}): SmartAccountOffer => ({
  available: true,
  canSubscribe: true,
  blockedReason: null,
  plans: [
    { key: 'monthly', priceUsd: '14.99', periodDays: 30, nextPriceUsd: null, nextPriceEffectiveAt: null, isDefault: false },
    { key: 'annual', priceUsd: '149.99', periodDays: 365, nextPriceUsd: null, nextPriceEffectiveAt: null, isDefault: true },
  ],
  headline: 'automation_first',
  benefits: [
    { key: 'payments', title: 'Pagos y transferencias automáticos', body: 'A quien tú elijas, con tu frecuencia.' },
    { key: 'investing', title: 'Inversión automática', body: 'Compra un poco cada cierto tiempo.' },
    { key: 'beneficiary', title: 'Beneficiario', body: 'Una persona recibe tu cuenta si dejas de usarla.' },
    { key: 'assistant', title: 'El asistente de tu cuenta', body: 'Analiza tus movimientos, te avisa y sigue tus metas.' },
  ],
  disclosures: ['Uno.', 'Dos.', 'Tres.', 'Cuatro.', 'Cinco.', 'Seis.'],
  beneficiaryEnabled: true,
  investingCryptoEnabled: true,
  payoutRails: ['co_breb'],
  dollar: 'cusd_plus',
  minFirstDepositUsd: '149.99',
  ...over,
});

export const rule = (over: Partial<SmartAccountRule> = {}): SmartAccountRule => ({
  id: 'r1', onchainId: '1', kind: 'send', frequency: 'weekly', amountUsd: '50.00', active: true,
  nextRunAt: '2026-12-01T12:00:00Z', lastRunAt: null, lastRunStatus: null, lastRunMessage: null,
  payeeName: 'Ana P.', payeeHandle: 'ana', payoutMethodId: null, payoutLabel: null, payoutRail: null,
  assetKey: null, assetSymbol: null, assetName: null,
  ...over,
});

export const beneficiary = (over: Partial<SmartAccountBeneficiary> = {}): SmartAccountBeneficiary => ({
  designationId: 'd1', state: 'active', name: 'Ana P.', handle: 'ana', windowDays: 180,
  designatedAt: '2026-11-01T12:00:00Z', acceptedAt: '2026-11-03T12:00:00Z', expiresAt: null,
  cooldownUntil: null, claim: null,
  ...over,
});

export const account = (over: Partial<SmartAccount> = {}): SmartAccount => ({
  status: 'active',
  contractAddress: '0x00000000000000000000000000000000000000aa',
  totalUsd: '1234.56',
  dollarsUsd: '1000.00',
  billing: {
    status: 'current', plan: 'annual', nextPlan: null, feeUsd: '149.99', paidUntil: '2027-11-20T12:00:00Z',
    cancelRequested: false, returnsAt: null, shortfallUsd: null, noticeStartedAt: null, saleAllowedAt: null,
    saleCandidates: null,
  },
  assets: [
    { key: 'cusd_plus', kind: 'dollar', symbol: 'cUSD+', name: 'cUSD+', address: '0x1', units: '1000000000000000000000', decimals: 18, valueUsd: '1000.00', canPayFee: true },
    { key: 'stock:AAPLon', kind: 'stock', symbol: 'AAPLon', name: 'Apple', address: '0x2', units: '1000000000000000000', decimals: 18, valueUsd: '234.56', canPayFee: true },
  ],
  rules: [],
  beneficiary: null,
  pendingBeneficiary: null,
  windowOptionsDays: [90, 180, 365],
  defaultWindowDays: 180,
  assistantPlus: true,
  ...over,
});

export const movePreview = (over: Partial<SmartAccountMovePreview> = {}): SmartAccountMovePreview => ({
  direction: 'in',
  assets: [
    { key: 'cusd_plus', symbol: 'cUSD+', name: 'cUSD+', units: '500000000000000000000', decimals: 18, valueUsd: '500.00', included: true, reason: null },
    { key: 'stock:AAPLon', symbol: 'AAPLon', name: 'Apple', units: '1000000000000000000', decimals: 18, valueUsd: '200.00', included: true, reason: null },
    { key: 'other:presale', symbol: 'CONFIO', name: 'CONFIO de preventa', units: '0', decimals: 18, valueUsd: null, included: false, reason: 'La preventa bloqueada no se puede mover.' },
  ],
  totalUsd: '700.00',
  batches: 1,
  ...over,
});

export const designation = (over: Partial<BeneficiaryDesignation> = {}): BeneficiaryDesignation => ({
  designationId: 'd1', state: 'pending_acceptance', ownerName: 'Luis R.', ownerHandle: 'luis', windowDays: 180,
  designatedAt: '2026-11-10T12:00:00Z', acceptedAt: null, expiresAt: '2026-12-10T12:00:00Z',
  contractAddress: null, chainName: null, cooldownUntil: null, claim: null, canClaim: false, canExecute: false,
  ...over,
});

export const inherited = (over: Partial<InheritedAccount> = {}): InheritedAccount => ({
  inheritedAccountId: 'i1', contractAddress: '0x00000000000000000000000000000000000000bb', fromName: 'Luis R.',
  inheritedAt: '2026-11-15T12:00:00Z', totalUsd: '321.00',
  assets: [
    { key: 'cusd', kind: 'dollar', symbol: 'cUSD', name: 'cUSD', address: '0x3', units: '321000000000000000000', decimals: 18, valueUsd: '321.00', canPayFee: true },
  ],
  canMoveToSmartAccount: true,
  ...over,
});

export const prepared = (over: Partial<SmartAccountPreparedBatch> = {}): SmartAccountPreparedBatch => ({
  success: true, errorCode: null, errorMessage: null, requestId: 'req_1',
  calls: [{ to: '0x00000000000000000000000000000000000000aa', valueWei: '0', data: '0x1234' }],
  notAfter: null, summary: ['Línea del servidor'],
  ...over,
});

export const refused = (message: string, code = 'refused'): SmartAccountPreparedBatch =>
  prepared({ success: false, errorCode: code, errorMessage: message, requestId: null, calls: null, summary: null });

// ------------------------------------------------------------- helpers

/** Every string drawn on screen, one per line (props are not included: a
 *  FlatList keeps React elements in them, which cannot be serialised). */
export const text = (tree: renderer.ReactTestRenderer): string => {
  const out: string[] = [];
  const walk = (node: unknown): void => {
    if (node === null || node === undefined) {
      return;
    }
    if (typeof node === 'string') {
      out.push(node);
    } else if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (typeof node === 'object') {
      walk((node as { children?: unknown }).children);
    }
  };
  walk(tree.toJSON());
  return out.join('\n');
};

const matches = (node: renderer.ReactTestInstance, idOrLabel: string) =>
  typeof node.props.onPress === 'function'
  && (node.props.testID === idOrLabel || node.props.accessibilityLabel === idOrLabel);

/** The pressable with this testID or accessibility label (throws when absent). */
export function tappable(tree: renderer.ReactTestRenderer, idOrLabel: string): renderer.ReactTestInstance {
  const found = tree.root.findAll((n) => matches(n, idOrLabel));
  if (found.length === 0) {
    throw new Error(`No tappable "${idOrLabel}"`);
  }
  return found[0];
}

export const hasTappable = (tree: renderer.ReactTestRenderer, idOrLabel: string): boolean =>
  tree.root.findAll((n) => matches(n, idOrLabel)).length > 0;

export async function tap(tree: renderer.ReactTestRenderer, idOrLabel: string): Promise<void> {
  await act(async () => {
    tappable(tree, idOrLabel).props.onPress();
  });
}

/** Let pending promises (reads, prepares, signatures) settle. */
export async function flush(times = 3): Promise<void> {
  for (let i = 0; i < times; i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}
