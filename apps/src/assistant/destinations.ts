// Screens Confio Assistant may open. Keys are a contract with the server
// (assistant/destinations.py): never rename, only add. Unknown keys are
// ignored, so an older build never breaks on a newer server.
//
// Money flows always land on the verb screen that owns their guards:
// Recargar lives inside Recibir and Retirar inside Enviar, so the AI can
// never skip the ramp-country / blocked-country checks those screens run.
import { navigationRef } from '../navigation/RootNavigation';
import { isBalanceHidden } from '../utils/balanceVisibility';
import { openRuleProposal } from './ruleProposal';
import { CONVERSATION_HOME_ENABLED } from '../config/features';
import { requestHomeMenu, requestHomeTile } from '../home/homeMoneyStore';

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
  // Descubrir is gone as a tab: its Comunidad lives in Invertir.
  discover: { tab: 'Invest', params: { segment: 'community' } },
  community: { tab: 'Invest', params: { segment: 'community' } },
  comprar: { tab: 'Comprar' },
  my_store: { screen: 'MyMarketStore' },
  market_orders: { screen: 'MarketOrders' },
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
  // Cuenta inteligente: this build always opens the real offer (which sends
  // a subscriber on to the account). Confío IA+ comes with Cuenta inteligente
  // (2026-10-17): same screen.
  ia_plus: { screen: 'SmartAccountOffer' },
  cuenta_inteligente: { screen: 'SmartAccountOffer' },
  // Confío IA+ rule proposal ("Revisar y firmar"): the rule screen, prefilled
  // from the proposal on that message (openRuleProposal). Without a message
  // id, the rules list. The server's fallback for older builds is
  // `cuenta_inteligente`.
  smart_account_rule: { screen: 'SmartAccountRules' },
  // Doors the menu and Perfil have, so that everything can be done from the
  // chat. On builds that predate a key the server's fallback opens instead.
  charge: { screen: 'Charge' },
  invite: { screen: 'Invite' },
  founder: { screen: 'Founder' },
  commissions: { screen: 'FeeReferralCommissions' },
  agenda: { screen: 'Agenda' },
  ramp_history: { screen: 'RampHistory' },
  // A wallet opens as its tile in the menu does (openDestination below).
  wallet_dollar: { tab: 'Home' },
  wallet_confio: { tab: 'Home' },
  stocks_activity: { screen: 'StocksActivity' },
  league: { screen: 'League' },
  community_post: { screen: 'CommunityCompose' },
  notification_settings: { screen: 'NotificationSettings' },
  edit_profile: { screen: 'EditProfile' },
  username: { screen: 'UpdateUsername' },
  share_username: { screen: 'ConfioAddress' },
  memberships: { screen: 'Memberships' },
  create_business: { screen: 'CreateBusiness' },
  payroll: { screen: 'PayrollHome' },
  employees: { screen: 'Employees' },
  terms: { screen: 'LegalDocument', params: { docType: 'terms' } },
};

// Opened only by a tap, never by an answer moving the app on its own: the
// offer, and a rule change the owner has to review and sign.
export const TAP_ONLY_KEYS = new Set(['ia_plus', 'cuenta_inteligente', 'smart_account_rule']);

// Keys whose screen is the Cuenta inteligente offer: opened only by a tap,
// never by a voice answer moving the app on its own.
export const PAID_OFFER_KEYS = new Set(['ia_plus', 'cuenta_inteligente']);

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
  // Descubrir is gone as a tab: the key opens Comunidad.
  discover: 'Abrir Comunidad',
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
  // Opens Cuenta inteligente (Confío IA+ is one of its benefits).
  ia_plus: 'Conoce Cuenta inteligente',
  cuenta_inteligente: 'Conoce Cuenta inteligente',
  smart_account_rule: 'Revisar y firmar',
  charge: 'Cobrar',
  invite: 'Invitar y ganar',
  founder: 'El fundador',
  commissions: 'Mis comisiones',
  agenda: 'Abrir Agenda',
  ramp_history: 'Recargas y retiros',
  wallet_dollar: 'Ver mi dólar',
  wallet_confio: 'Ver mis $CONFIO',
  stocks_activity: 'Mis operaciones',
  league: 'Ver la Liga',
  community_post: 'Publicar en Comunidad',
  notification_settings: 'Ajustes de avisos',
  edit_profile: 'Editar perfil',
  username: 'Cambiar mi usuario',
  share_username: 'Compartir mi usuario',
  memberships: 'Mis instituciones',
  create_business: 'Crear cuenta de negocio',
  payroll: 'Abrir Nómina',
  employees: 'Ver empleados',
  terms: 'Términos y condiciones',
  // Keys that never had a label of their own (they showed nothing).
  community: 'Abrir Comunidad',
  comprar: 'Abrir Comprar',
  my_store: 'Mi tienda',
  market_orders: 'Mis compras y ventas',
};

// A card in the conversation: the screen's icon, its name and one line of
// what the person does there. Every key has one.
// The card is named by the action's own label ("Abrir Recibir", "Ver S&P 500
// (SPY)"); `hint` is the one line under it, short enough for one line on a
// small phone. `icon` is a Feather name, or one of the app's own marks:
// 'qr-pay' and 'qr-show' are the icons Pagar and Cobrar wear everywhere,
// 'smart-account' the Cuenta inteligente mark.
export type DestinationCard = { icon: string; hint: string };

export const DESTINATION_CARDS: Record<string, DestinationCard> = {
  home: { icon: 'credit-card', hint: 'Tu saldo y tus billeteras' },
  pay_qr: { icon: 'qr-pay', hint: 'Escanea un QR y paga' },
  send: { icon: 'arrow-up-right', hint: 'A un contacto o a tu banco' },
  receive: { icon: 'arrow-down-left', hint: 'Tu número Confío y tus cuentas' },
  top_up: { icon: 'arrow-down-circle', hint: 'Pon dólares desde tu banco' },
  withdraw: { icon: 'arrow-up-circle', hint: 'Lleva dólares a tu banco' },
  invest: { icon: 'trending-up', hint: 'Acciones de EE.UU. y más' },
  stocks: { icon: 'bar-chart-2', hint: 'La lista de acciones y ETF' },
  presale: { icon: 'award', hint: 'Antes del lanzamiento' },
  discover: { icon: 'users', hint: 'Lo que comparten los miembros' },
  community: { icon: 'users', hint: 'Lo que comparten los miembros' },
  comprar: { icon: 'shopping-bag', hint: 'De vendedores verificados' },
  my_store: { icon: 'tag', hint: 'Publica y vende tus productos' },
  market_orders: { icon: 'package', hint: 'Lo que compraste y vendiste' },
  profile: { icon: 'user', hint: 'Identidad, seguridad y ajustes' },
  verification: { icon: 'shield', hint: 'Con tu documento y una selfie' },
  cash_directory: { icon: 'map-pin', hint: 'Casas de cambio y agentes' },
  messages: { icon: 'message-circle', hint: 'Julian, News y tus mensajes' },
  notifications: { icon: 'bell', hint: 'Tus avisos recientes' },
  achievements: { icon: 'star', hint: 'Tus logros y recompensas' },
  pending_incoming: { icon: 'download', hint: 'Esperan tu confirmación' },
  stock: { icon: 'activity', hint: 'Precio, gráfico y comprar' },
  month_summary: { icon: 'pie-chart', hint: 'Lo que entró y salió este mes' },
  emergency_exit: { icon: 'life-buoy', hint: 'Saca tu dinero sin Confío' },
  tokenomics: { icon: 'layers', hint: 'Suministro y distribución' },
  ia_plus: { icon: 'smart-account', hint: 'Pagos e inversión automáticos' },
  cuenta_inteligente: { icon: 'smart-account', hint: 'Pagos e inversión automáticos' },
  smart_account_rule: { icon: 'edit-3', hint: 'Revísalo antes de firmar' },
  charge: { icon: 'qr-show', hint: 'Muestra un QR y te pagan' },
  invite: { icon: 'gift', hint: 'Invita y gana en dólares' },
  founder: { icon: 'heart', hint: 'Julian Moon y sus canales' },
  commissions: { icon: 'percent', hint: 'Lo que ganaste por invitar' },
  agenda: { icon: 'book', hint: 'Cuentas y contactos guardados' },
  ramp_history: { icon: 'clock', hint: 'El historial con tu banco' },
  wallet_dollar: { icon: 'dollar-sign', hint: 'Su saldo y sus movimientos' },
  wallet_confio: { icon: 'disc', hint: 'Tu saldo y su historial' },
  stocks_activity: { icon: 'list', hint: 'Tus compras y ventas' },
  league: { icon: 'flag', hint: 'El ranking de inversores' },
  community_post: { icon: 'edit', hint: 'Escribe una publicación' },
  notification_settings: { icon: 'sliders', hint: 'Elige qué avisos recibes' },
  edit_profile: { icon: 'edit-2', hint: 'Cambia tus datos' },
  username: { icon: 'at-sign', hint: 'También es tu código' },
  share_username: { icon: 'share-2', hint: 'Tu @usuario y tu QR' },
  memberships: { icon: 'link', hint: 'Instituciones vinculadas' },
  create_business: { icon: 'briefcase', hint: 'Una cuenta para tu negocio' },
  payroll: { icon: 'clipboard', hint: 'Paga a tu equipo' },
  employees: { icon: 'user-plus', hint: 'Tu equipo y sus permisos' },
  terms: { icon: 'file-text', hint: 'Las condiciones de uso' },
};

// What the conversation home's own keys say on their card.
const CONVERSATION_CARDS: Record<string, DestinationCard> = {
  home: { icon: 'credit-card', hint: 'Tu saldo y tus billeteras' },
};

export function cardFor(key: string): DestinationCard {
  return (CONVERSATION_HOME_ENABLED && CONVERSATION_CARDS[key]) || DESTINATION_CARDS[key]
    || { icon: 'arrow-up-right', hint: '' };
}

// In the conversation home Inicio is the chat itself: `home` opens the menu, where the money is.
const CONVERSATION_LABELS: Record<string, string> = { home: 'Ver mi dinero' };

function labelFor(key: string): string {
  return (CONVERSATION_HOME_ENABLED && CONVERSATION_LABELS[key]) || DESTINATION_LABELS[key];
}

export type NavigateAction = { destination?: string | null; target?: string | null; ticker?: string | null; label?: string | null };

// The screen a navigate action opens on this build: its newer `target` when
// this build knows it (a stock page needs its ticker), else `destination`,
// the fallback every build knows. Null when neither is known.
export function resolveNavigate(a: NavigateAction): { key: string; ticker?: string; label: string } | null {
  if (isKnownDestination(a.target) && (a.target !== 'stock' || a.ticker)) {
    // Offer chips always carry the offer's current name: a reply stored
    // before a rename ("Conoce Confío IA+") must not show the old one.
    const label = PAID_OFFER_KEYS.has(a.target) ? DESTINATION_LABELS[a.target] : a.label || labelFor(a.target);
    return { key: a.target, ticker: a.ticker ?? undefined, label };
  }
  if (isKnownDestination(a.destination) && a.destination !== 'stock') {
    return { key: a.destination, label: labelFor(a.destination) };
  }
  return null;
}

// Own keys only: `in` would also accept prototype names ("constructor").
export function isKnownDestination(key?: string | null): key is string {
  return !!key && Object.prototype.hasOwnProperty.call(DESTINATION_TARGETS, key);
}

export function openDestination(
  key: string,
  opts: { isBusiness?: boolean; ticker?: string; messageId?: string } = {},
): boolean {
  if (key === 'smart_account_rule') {
    if (!navigationRef.isReady()) {
      return false;
    }
    void openRuleProposal(opts.messageId);
    return true;
  }
  let target = isKnownDestination(key) ? DESTINATION_TARGETS[key] : undefined;
  if (key === 'stock') {
    target = opts.ticker ? { screen: 'StockDetail', params: { ticker: opts.ticker } } : undefined;
  }
  if (target && 'screen' in target && PAID_OFFER_KEYS.has(key)) {
    // From Confio Assistant a pitch is always a chip; the server knows why it
    // showed it and records that on the waitlist row.
    target = { screen: target.screen, params: { ...(target.params ?? {}), door: 'chip' } };
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
  // In the conversation home Inicio is the chat itself: "show me my money"
  // opens the menu, where the money is (a Cuenta inteligente context has no
  // menu and keeps its own home).
  if (key === 'home' && CONVERSATION_HOME_ENABLED && requestHomeMenu()) {
    return true;
  }
  if (key === 'wallet_dollar' || key === 'wallet_confio') {
    // The wallet's own screen, opened as its tile in the menu opens it (the
    // name and figures it needs are Inicio's). Not there to open (the five
    // tabs, a Cuenta inteligente context): the menu, or Inicio, has it.
    if (CONVERSATION_HOME_ENABLED && (requestHomeTile(key === 'wallet_dollar' ? 'dollar' : 'confio') || requestHomeMenu())) {
      return true;
    }
  }
  if (key === 'edit_profile' && opts.isBusiness) {
    target = { screen: 'EditBusiness' };
  }
  if (key === 'invest' || (CONVERSATION_HOME_ENABLED && (key === 'stocks' || key === 'presale'))) {
    // Comunidad may be the open segment: `at` asks for Invertir even so. In
    // the conversation home there is no segment bar to switch back with, so
    // every key that lives in Invertir asks for it by name.
    target = { tab: 'Invest', params: { segment: 'invest', at: Date.now() } };
  }
  if ('tab' in target) {
    // Business accounts have Cobrar where personal accounts have Pagar.
    const tab = target.tab === 'Scan' && opts.isBusiness ? 'Charge' : target.tab;
    if (tab === 'Scan' && CONVERSATION_HOME_ENABLED) {
      // No Pagar tab in the conversation home: the scanner is a stack screen.
      (navigationRef as any).navigate('Main', { screen: 'Scan', params: { mode: 'pagar', ...target.params } });
      return true;
    }
    (navigationRef as any).navigate('Main', {
      screen: 'BottomTabs',
      params: { screen: tab, params: target.params },
    });
  } else {
    (navigationRef as any).navigate('Main', { screen: target.screen, params: target.params });
  }
  return true;
}
