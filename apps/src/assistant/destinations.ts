// Screens Confio Assistant may open. Keys are a contract with the server
// (assistant/destinations.py): never rename, only add. Unknown keys are
// ignored, so an older build never breaks on a newer server.
//
// Money flows always land on the verb screen that owns their guards:
// Recargar lives inside Recibir and Retirar inside Enviar, so the AI can
// never skip the ramp-country / blocked-country checks those screens run.
import { navigationRef } from '../navigation/RootNavigation';

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
};

export function isKnownDestination(key?: string | null): key is string {
  return !!key && key in DESTINATION_TARGETS;
}

export function openDestination(key: string, opts: { isBusiness?: boolean } = {}): boolean {
  const target = DESTINATION_TARGETS[key];
  if (!target || !navigationRef.isReady()) {
    return false;
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
