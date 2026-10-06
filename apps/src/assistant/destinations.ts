// Screens Confio Assistant may open. Keys are a contract with the server
// (assistant/destinations.py): never rename, only add. Unknown keys are
// ignored, so an older build never breaks on a newer server.
//
// Money flows always land on the verb screen that owns their guards:
// Recargar lives inside Recibir and Retirar inside Enviar, so the AI can
// never skip the ramp-country / blocked-country checks those screens run.
import { navigationRef } from '../navigation/RootNavigation';
import { isBalanceHidden } from '../utils/balanceVisibility';

type Target =
  | { tab: string; params?: object }
  | { screen: string; params?: object };

export const DESTINATION_TARGETS: Record<string, Target> = {
  home: { tab: 'Home' },
  pay_qr: { tab: 'Scan' },
  send: { screen: 'Send' },
  receive: { screen: 'Receive' },
  top_up: { screen: 'Receive' },
  withdraw: { screen: 'Send' },
  invest: { tab: 'Invest' },
  // Stocks and presale are geo-gated: the Invertir tab decides what to show.
  stocks: { tab: 'Invest' },
  presale: { tab: 'Invest' },
  discover: { tab: 'Discover' },
  profile: { tab: 'Profile' },
  verification: { screen: 'Verification' },
  cash_directory: { screen: 'Financieras' },
  messages: { screen: 'HomeMessages' },
  notifications: { screen: 'Notification' },
  achievements: { screen: 'Achievements' },
  pending_incoming: { screen: 'PendingIncoming' },
  // A single stock's page; the action carries the ticker. The screen shows
  // its own "not available" state where stocks aren't offered.
  stock: { screen: 'StockDetail' },
  month_summary: { screen: 'MonthSummary' },
  emergency_exit: { screen: 'EmergencyExit' },
  tokenomics: { screen: 'ConfioTokenomics' },
};

export const DESTINATION_LABELS: Record<string, string> = {
  home: 'Ir a Inicio',
  pay_qr: 'Abrir Pagar',
  send: 'Abrir Enviar',
  receive: 'Abrir Recibir',
  top_up: 'Recargar',
  withdraw: 'Retirar',
  invest: 'Abrir Invertir',
  stocks: 'Ver acciones',
  presale: 'Ver preventa',
  discover: 'Abrir Descubrir',
  profile: 'Abrir Perfil',
  verification: 'Verificar identidad',
  cash_directory: 'Ver efectivo',
  messages: 'Abrir Mensajes',
  notifications: 'Ver notificaciones',
  achievements: 'Ver logros',
  pending_incoming: 'Ver dinero por recibir',
  stock: 'Ver acción',
  month_summary: 'Ver Tu mes',
  emergency_exit: 'Salida de emergencia',
  tokenomics: 'Ver tokenomics',
};

export type NavigateAction = { destination?: string | null; target?: string | null; ticker?: string | null; label?: string | null };

// The screen a navigate action opens on this build: its newer `target` when
// this build knows it (a stock page needs its ticker), else `destination`,
// the fallback every build knows. Null when neither is known.
export function resolveNavigate(a: NavigateAction): { key: string; ticker?: string; label: string } | null {
  if (isKnownDestination(a.target) && (a.target !== 'stock' || a.ticker)) {
    return { key: a.target, ticker: a.ticker ?? undefined, label: a.label || DESTINATION_LABELS[a.target] };
  }
  if (isKnownDestination(a.destination) && a.destination !== 'stock') {
    return { key: a.destination, label: DESTINATION_LABELS[a.destination] };
  }
  return null;
}

// Own keys only: `in` would also accept prototype names ("constructor").
export function isKnownDestination(key?: string | null): key is string {
  return !!key && Object.prototype.hasOwnProperty.call(DESTINATION_TARGETS, key);
}

export function openDestination(key: string, opts: { isBusiness?: boolean; ticker?: string } = {}): boolean {
  let target = isKnownDestination(key) ? DESTINATION_TARGETS[key] : undefined;
  if (key === 'stock') {
    target = opts.ticker ? { screen: 'StockDetail', params: { ticker: opts.ticker } } : undefined;
  }
  if (!target || !navigationRef.isReady()) {
    return false;
  }
  if (key === 'month_summary') {
    // Same privacy as opening it from Inicio: amounts stay hidden when the
    // person hid their balance (read exactly as Home reads it).
    void isBalanceHidden().then((masked) => {
      (navigationRef as any).navigate('Main', { screen: 'MonthSummary', params: { masked } });
    });
    return true;
  }
  if ('tab' in target) {
    // Business accounts have Cobrar where personal accounts have Pagar.
    const tab = target.tab === 'Scan' && opts.isBusiness ? 'Charge' : target.tab;
    (navigationRef as any).navigate('Main', {
      screen: 'BottomTabs',
      params: { screen: tab, params: target.params },
    });
  } else {
    (navigationRef as any).navigate('Main', { screen: target.screen, params: target.params });
  }
  return true;
}
