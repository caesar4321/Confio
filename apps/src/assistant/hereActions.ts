// What a person finishes right in the chat: a card whose button does the
// thing on this phone, with no other screen (assistant/here.py). The
// assistant only proposes; the tap is the person's own decision, and a
// change goes through the same mutations the app's screens use.
//
// An action arrives as { type: 'do', target: '<key>[:<argument>]', label }.
import type { ApolloClient } from '@apollo/client';
import { UPDATE_USERNAME } from '../apollo/queries';
import { SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR, SET_DIRECT_MESSAGES_ENABLED, SET_REFERRER } from '../apollo/mutations';
import { UPDATE_ASSISTANT_PROFILE } from './api';
import { UPDATE_NOTIFICATION_PREFERENCES } from '../graphql/mutations/notifications';
import { GET_NOTIFICATION_PREFERENCES } from '../graphql/queries/notifications';
import { shareOwnUsername, shareReferralOnWhatsApp } from '../services/referralShare';

export type HereAction = { key: string; arg?: string; label: string };

// `changes`: tapping it changes something of the person's (the card then
// says so); the others open WhatsApp, the share sheet or the pet's picker
// and change nothing by themselves.
export const HERE_CARDS: Record<string, { icon: string; hint: string; changes?: boolean }> = {
  invite_whatsapp: { icon: 'whatsapp', hint: 'Tu enlace y tu código, listos' },
  share_username: { icon: 'share-2', hint: 'Para que te envíen dinero' },
  set_username: { icon: 'at-sign', hint: 'También cambia tu código', changes: true },
  set_notifications: { icon: 'bell', hint: 'Se cambia al tocar', changes: true },
  // Opens the pet's picker over the chat: character, color, name, or one of their own.
  customize_pet: { icon: 'smile', hint: 'Personaje, color y nombre' },
  set_pet_name: { icon: 'edit-3', hint: 'Se cambia al tocar', changes: true },
  set_messages: { icon: 'message-circle', hint: 'Se cambia al tocar', changes: true },
  set_investor_profile: { icon: 'eye', hint: 'Se cambia al tocar', changes: true },
  set_referrer: { icon: 'user-plus', hint: 'Se registra una sola vez', changes: true },
  // Opens Recargar with the amount the person wrote already filled in.
  top_up: { icon: 'arrow-down-circle', hint: 'Con el monto ya escrito' },
};
const TOP_UP = /^([A-Z]{3})=(\d{1,9}(?:\.\d{1,2})?)$/;
export const PET_NAME_MAX = 24;

const NOTIFICATION_VARIABLES: Record<string, string> = {
  all: 'pushEnabled',
  transactions: 'pushTransactions',
  p2p: 'pushP2p',
  promotions: 'pushPromotions',
  announcements: 'pushAnnouncements',
  in_app: 'inAppEnabled',
};
// Keys that take no argument, and the ones whose argument is one of a few words.
const BARE = new Set(['invite_whatsapp', 'share_username', 'customize_pet']);
const WORDS: Record<string, string[]> = {
  set_messages: ['on', 'off'],
  set_investor_profile: ['public', 'hidden'],
};
const USERNAME = /^[A-Za-z0-9_]{3,20}$/;
const SWITCH = /^([a-z_0-9]+)=(on|off)$/;

/** The action as this build knows it; null for anything else (an unknown key,
 * an argument that is not what the key takes). */
export function resolveHere(a: { type: string; target?: string | null; label?: string | null }): HereAction | null {
  if (a.type !== 'do' || !a.target || !a.label) {
    return null;
  }
  const at = a.target.indexOf(':');
  const key = at < 0 ? a.target : a.target.slice(0, at);
  const arg = at < 0 ? undefined : a.target.slice(at + 1);
  if (!Object.prototype.hasOwnProperty.call(HERE_CARDS, key)) {
    return null;
  }
  if (key === 'set_username' && !(arg && USERNAME.test(arg))) {
    return null;
  }
  if (key === 'set_notifications') {
    const parts = arg ? SWITCH.exec(arg) : null;
    if (!parts || !NOTIFICATION_VARIABLES[parts[1]]) {
      return null;
    }
  }
  if (key === 'set_referrer' && !(arg && USERNAME.test(arg))) {
    return null;
  }
  if (key === 'set_pet_name' && !(arg && arg.trim() === arg && arg.length <= PET_NAME_MAX)) {
    return null;
  }
  if (WORDS[key] && !(arg && WORDS[key].includes(arg))) {
    return null;
  }
  if (key === 'top_up' && !(arg && TOP_UP.test(arg))) {
    return null;
  }
  if (BARE.has(key) && arg !== undefined) {
    return null;
  }
  return { key, arg, label: a.label };
}

export type HereContext = {
  username?: string | null;
  client: Pick<ApolloClient<unknown>, 'mutate'>;
  /** After a change to the profile, so the rest of the app shows it. */
  refreshProfile?: () => Promise<void>;
  /** Opens the pet's picker over the conversation. */
  openPetPicker?: () => void;
  /** The pet changed: the conversation reads it again. */
  onPetChanged?: () => void;
  /** The phone's own permission for alerts: a switch turned on in Confío
   * shows nothing while the phone blocks them. */
  phoneAlerts?: { enabled: () => Promise<boolean>; request: () => Promise<boolean> };
  /** Opens one of the app's screens (the card leaves the conversation). */
  openScreen?: (screen: string, params: Record<string, unknown>) => void;
};

/** Does it. `done` / `error` is said on the card of an action that changes
 * something; null for the ones that only open WhatsApp or the share sheet. */
export async function runHere(action: HereAction, context: HereContext): Promise<{ done?: string; error?: string } | null> {
  if (action.key === 'invite_whatsapp') {
    await shareReferralOnWhatsApp(context.username, 'chat');
    return null;
  }
  if (action.key === 'share_username') {
    return (await shareOwnUsername(context.username)) ? null : { error: 'Primero crea tu @usuario.' };
  }
  if (action.key === 'customize_pet') {
    context.openPetPicker?.();
    return null;
  }
  if (action.key === 'top_up') {
    const [, currency, amount] = TOP_UP.exec(action.arg || '') || [];
    // The screen fills it in only if it is in this currency (TopUpScreen).
    context.openScreen?.('TopUp', { amount, amountCurrency: currency });
    return null;
  }
  try {
    if (action.key === 'set_pet_name') {
      const { data } = await context.client.mutate({ mutation: UPDATE_ASSISTANT_PROFILE, variables: { mascotName: action.arg } });
      if (!(data as any)?.updateAssistantProfile?.success) {
        return { error: 'No se pudo cambiar. Inténtalo de nuevo.' };
      }
      context.onPetChanged?.();
      return { done: `Listo: ahora me llamo ${action.arg}` };
    }
    if (action.key === 'set_messages') {
      const on = action.arg === 'on';
      const { data } = await context.client.mutate({ mutation: SET_DIRECT_MESSAGES_ENABLED, variables: { enabled: on } });
      const result = (data as any)?.setDirectMessagesEnabled;
      if (!result?.success || Boolean(result.enabled) !== on) {
        return { error: 'No se pudo cambiar. Inténtalo de nuevo.' };
      }
      return { done: on ? 'Listo: pueden escribirte personas nuevas' : 'Listo: nadie nuevo podrá escribirte' };
    }
    if (action.key === 'set_investor_profile') {
      const hidden = action.arg === 'hidden';
      const { data } = await context.client.mutate({ mutation: SET_COMMUNITY_PORTFOLIO_HIDDEN_WITH_ERROR, variables: { hidden } });
      const result = (data as any)?.setCommunityPortfolioHidden;
      if (!result?.success || Boolean(result.hidden) !== hidden) {
        return { error: result?.error || 'No se pudo cambiar. Inténtalo de nuevo.' };
      }
      return { done: hidden ? 'Listo: tu perfil de inversor está oculto' : 'Listo: tu perfil de inversor es público' };
    }
    if (action.key === 'set_referrer') {
      const { data } = await context.client.mutate({ mutation: SET_REFERRER, variables: { referrerIdentifier: action.arg } });
      const result = (data as any)?.setReferrer;
      if (!result?.success) {
        return { error: result?.error || 'No se pudo registrar. Inténtalo de nuevo.' };
      }
      return { done: `Listo: registré a @${action.arg}` };
    }
    if (action.key === 'set_username') {
      const { data } = await context.client.mutate({ mutation: UPDATE_USERNAME, variables: { username: action.arg } });
      const result = (data as any)?.updateUsername;
      if (!result?.success) {
        return { error: result?.error || 'No se pudo cambiar. Prueba con otro nombre.' };
      }
      await context.refreshProfile?.().catch(() => {});
      return { done: `Listo: ahora eres @${action.arg}` };
    }
    if (action.key === 'set_notifications') {
      const [, setting, state] = SWITCH.exec(action.arg || '') || [];
      const { data } = await context.client.mutate({
        mutation: UPDATE_NOTIFICATION_PREFERENCES,
        variables: { [NOTIFICATION_VARIABLES[setting]]: state === 'on' },
        refetchQueries: [{ query: GET_NOTIFICATION_PREFERENCES }],
      });
      if (!(data as any)?.updateNotificationPreferences?.success) {
        return { error: 'No se pudo cambiar. Inténtalo de nuevo.' };
      }
      if (state === 'on' && setting !== 'in_app' && context.phoneAlerts) {
        // As the settings screen: ask the phone too, and say so if it says no.
        const allowed = await context.phoneAlerts.enabled().catch(() => true)
          || await context.phoneAlerts.request().catch(() => true);
        if (!allowed) {
          return { done: 'Listo. Falta permitirlas en los ajustes de tu teléfono.' };
        }
      }
      return { done: state === 'on' ? 'Listo: activadas' : 'Listo: apagadas' };
    }
  } catch (_e) {
    return { error: 'Sin conexión. Inténtalo de nuevo.' };
  }
  return null;
}
