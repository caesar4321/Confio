// What the conversation home's header and drawer say about the person's
// money, from the figures HomeScreen already holds. Pure, so the rules are
// testable: a hidden balance masks every amount, an unknown one is a dash and
// never a zero, and an offer never looks like a balance.
import type { HeroMonthState } from '../hooks/useMonthHeroLine';
import { formatDecimal, formatUsdAmount } from '../utils/numberLocale';
import type { HomeAccount, HomeMoney, HomeMoneyTile } from './homeMoneyStore';

const MASK = '••••';
const UNKNOWN = '—';

export type HomeMoneyInput = {
  /** The first balances answer has arrived. */
  ready: boolean;
  /** Hidden by the eye, or an employee without viewBalance. */
  masked: boolean;
  canToggle: boolean;
  /** The total, already formatted in the currency the person chose (never
   * masked here: the mask is applied below). */
  totalText: string;
  /** "USD" / "BOB"; null where there is no local currency to switch to. */
  currencyCode: string | null;
  currencyHint: string;
  accounts: HomeAccount[];
  month: HeroMonthState;
  /** Both balance reads are in: wallets are drawn only then. */
  balancesKnown: boolean;
  /** The dollar slot: "Confío Dollar+" where it is offered, "Confío Dollar" otherwise. */
  dollar: { plus: boolean; usd: number };
  /** Legacy cUSD; null once the row is gone. */
  legacyDollarUsd: number | null;
  investments: { visible: boolean; totalKnown: boolean; totalUsd: number };
  /** $CONFIO owned; null while unknown. */
  confioTotal: number | null;
  /** Cuenta inteligente; null for accounts that never see it. */
  smart: { known?: boolean; subscriber: boolean; totalUsd: string | number | null; canSubscribe: boolean } | null;
  actionIds: ('send' | 'receive')[];
  primaryAction: 'send' | 'receive';
  noticeKey: 'pendingIncoming' | 'inviteClaim' | 'payroll' | 'presaleClaim' | 'dues' | 'humanitarian' | null;
  pendingPayrollCount: number;
  /** The active campaign's own title (the `humanitarian` notice). */
  campaignTitle?: string | null;
};

/** Floors, never rounds up: a balance is not overstated by half a cent. */
function floor2(value: number) {
  return Number.isFinite(value) ? Math.floor(value * 100) / 100 : 0;
}

const NOTICES = {
  pendingIncoming: { icon: 'download', text: () => 'Tienes dinero por recibir' },
  inviteClaim: { icon: 'gift', text: () => 'Reclama fondos pendientes' },
  payroll: {
    icon: 'briefcase',
    text: (input: HomeMoneyInput) => (input.pendingPayrollCount === 1
      ? 'Tienes 1 pago de nómina para firmar' : `Tienes ${input.pendingPayrollCount} pagos de nómina para firmar`),
  },
  presaleClaim: { icon: 'award', text: () => 'Reclama tus $CONFIO' },
  dues: { icon: 'calendar', text: () => 'Tienes una cuota por pagar' },
  // The campaign Inicio used to show as a banner: same priority (last).
  humanitarian: {
    icon: 'heart',
    text: (input: HomeMoneyInput) => (input.campaignTitle?.trim()
      ? `Ayuda humanitaria: ${input.campaignTitle.trim()}` : 'Ayuda humanitaria directa'),
  },
} as const;

export function buildHomeMoney(
  input: HomeMoneyInput, call: (key: string) => () => void | Promise<void>,
): HomeMoney {
  const { masked } = input;
  const usd = (value: number) => (masked ? MASK : formatUsdAmount(floor2(value), { decimals: 2 }));
  const spoken = (amount: string) => (masked ? 'saldo oculto' : amount);
  const tiles: HomeMoneyTile[] = [];
  if (input.balancesKnown) {
    const dollarName = input.dollar.plus ? 'Confío Dollar+' : 'Confío Dollar';
    const dollarAmount = usd(input.dollar.usd);
    tiles.push({
      key: 'dollar', label: dollarName, amount: dollarAmount,
      accessibilityLabel: `${dollarName}, ${spoken(dollarAmount)}`, onPress: call('dollar'),
    });
    if (input.legacyDollarUsd !== null) {
      const amount = usd(input.legacyDollarUsd);
      tiles.push({
        key: 'legacy', label: 'Antiguo Confío Dollar', amount,
        accessibilityLabel: `Antiguo Confío Dollar, ${spoken(amount)}`, onPress: call('legacy'),
      });
    }
    if (input.investments.visible) {
      const amount = masked ? MASK : input.investments.totalKnown ? usd(input.investments.totalUsd) : UNKNOWN;
      tiles.push({
        key: 'invest', label: 'Inversiones', amount,
        accessibilityLabel: `Inversiones, ${spoken(amount === UNKNOWN ? 'saldo no disponible' : amount)}`, onPress: call('invest'),
      });
    }
    // A token count, not dollars: no currency sign.
    const confio = masked ? MASK : input.confioTotal === null ? UNKNOWN : formatDecimal(floor2(input.confioTotal), { decimals: 2 });
    tiles.push({
      key: 'confio', label: '$CONFIO', amount: confio,
      accessibilityLabel: `Confío, ${spoken(confio === UNKNOWN ? 'saldo no disponible' : `${confio} CONFIO`)}`, onPress: call('confio'),
    });
    // Last, and only a subscriber's has a number (the account's own total).
    if (input.smart) {
      if (input.smart.known === false) {
        // Same tile, same place, a dash: it becomes the balance or the offer
        // without the strip moving.
        tiles.push({
          key: 'smart', label: 'Cuenta inteligente', amount: UNKNOWN,
          accessibilityLabel: 'Cuenta inteligente, cargando', onPress: call('smart'),
        });
      } else if (input.smart.subscriber) {
        const total = input.smart.totalUsd === null ? NaN : Number(input.smart.totalUsd);
        const amount = masked ? MASK : Number.isFinite(total) ? usd(total) : UNKNOWN;
        tiles.push({
          key: 'smart', label: 'Cuenta inteligente', amount,
          accessibilityLabel: `Cuenta inteligente, ${spoken(amount === UNKNOWN ? 'saldo no disponible' : amount)}`, onPress: call('smart'),
        });
      } else {
        tiles.push({
          key: 'smart', label: 'Cuenta inteligente', amount: null,
          offerLabel: input.smart.canSubscribe ? 'Activar' : 'Ver',
          accessibilityLabel: 'Cuenta inteligente, pagos e inversión automáticos', onPress: call('smart'),
        });
      }
    }
  }
  const notice = input.noticeKey ? NOTICES[input.noticeKey] : null;
  return {
    ready: input.ready,
    total: masked ? '••••••' : input.totalText,
    masked,
    canToggle: input.canToggle,
    toggleBalance: call('toggleBalance'),
    currencyCode: input.currencyCode,
    currencyHint: input.currencyHint,
    toggleCurrency: call('toggleCurrency'),
    refresh: call('refresh'),
    pull: call('pull'),
    accounts: input.accounts,
    // One handler per account, named by its id.
    switchAccount: (id: string) => call(`switchAccount:${id}`)(),
    createBusiness: call('createBusiness'),
    month: input.month,
    openMonth: call('openMonth'),
    tiles,
    // The menu's Cuenta inteligente row: there from the start, not only once
    // the balances are in (it would push every row below it down).
    openSmart: input.smart ? call('smart') : null,
    actions: input.actionIds.map((id) => ({
      id,
      label: id === 'send' ? 'Enviar' : 'Recibir',
      icon: id === 'send' ? 'arrow-up-right' : 'arrow-down-left',
      // Positions never swap; only the emphasis moves. A lone verb is the filled one.
      filled: id === input.primaryAction || input.actionIds.length === 1,
      onPress: call(id),
    })),
    notice: notice && input.noticeKey
      ? { key: input.noticeKey, icon: notice.icon, text: notice.text(input), onPress: call(input.noticeKey) }
      : null,
  };
}
