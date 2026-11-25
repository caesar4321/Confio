// What the WhatsApp screens say, decided here so it can be tested without a screen. Copy is written here,
// never by the model: a model's summary is shown as a claim ("Parece…"), never as fact.
import type { WhatsAppDraft, WhatsAppLink } from './api';

/** What anyone reads before linking: three lines, in plain words. */
export const CONSENT_POINTS: { icon: string; text: string }[] = [
  { icon: 'bell', text: 'Te avisamos de cobros, pedidos y citas.' },
  { icon: 'check-circle', text: 'Respondes desde aquí. Nada sale sin tu OK.' },
  { icon: 'eye-off', text: 'No marcamos nada como leído ni apareces «en línea».' },
];
/** Always in sight before linking: what is read, by whom, for how long. */
export const CONSENT_DATA = 'Recibimos los mensajes de tus chats personales (no grupos) mientras siga vinculado. '
  + 'Guardamos cifradas las últimas 48 horas de cada chat para entender la conversación; una IA marca lo '
  + 'importante y lo guardamos cifrado mientras siga vinculado. '
  + 'Al vincularlo te dejamos una nota en tu propio chat, para que sepas que se vinculó.';

/** A number with its country code, as WhatsApp takes it: + and 8 to 15 digits. */
export const validPhone = (value: string) => /^\+\d{8,15}$/.test(value.replace(/[\s\-().]/g, ''));

/** The whole text the person accepts, behind "Cómo funciona". Version WHATSAPP_CONSENT_VERSION in api.ts:
 * a change in what Confío does with the account needs a new version there and on the server. What WhatsApp
 * may do to an account is in the Terms of Service (section 16), not here: moving it there changed nothing
 * Confío does, so the version stayed. */
export function consentText(): string[] {
  return [
    'Escribes tu número de WhatsApp y WhatsApp te pide confirmarlo con un código en tu teléfono. Confío lo '
      + 'vincula como un dispositivo más, desde servidores de Confío, solo para ti. Lo verás en WhatsApp como '
      + '«Chrome» en Dispositivos vinculados.',
    'Al vincularlo, Confío escribe una sola nota en tu chat contigo mismo («Mensaje para ti») diciendo que se '
      + 'vinculó: si alguien te pidió el código con engaños, lo ves ahí. Es el único mensaje que Confío escribe sin '
      + 'que lo apruebes.',
    'Mientras siga vinculado, recibimos los mensajes de tus chats personales, como cualquier dispositivo '
      + 'vinculado: los que te escriben y los que tú envías desde tu teléfono. No recibimos grupos ni estados, no '
      + 'marcamos nada como leído y no apareces «en línea». Los mensajes que parecen códigos o contraseñas se '
      + 'descartan sin guardarse.',
    'Guardamos cifradas las últimas 48 horas de cada chat, para entender la conversación completa (los mensajes '
      + 'partidos, lo que ya respondiste) y no sugerirte algo fuera de contexto; lo más antiguo se borra solo.',
    'Un modelo de IA lee esa conversación, marca lo importante (cobros, pedidos, entregas, citas, alguien '
      + 'esperando tu respuesta) y te lo cuento en nuestra conversación, con respuestas sugeridas. Guardamos lo '
      + 'importante, cifrado, mientras tu WhatsApp siga vinculado. Al desvincularlo, desde Confío o desde tu '
      + 'teléfono, lo borramos todo.',
    'Solo enviamos un mensaje cuando tú lo apruebas aquí, uno por uno y a ritmo de persona. Nunca pagamos nada '
      + 'desde WhatsApp.',
    'Puedes desvincularlo cuando quieras, aquí o desde tu teléfono.',
  ];
}

export type WhatsAppView = {
  badge?: string;
  body: string;
  action?: 'link' | 'open' | 'accept';
  actionLabel?: string;
};

/** The row in "WhatsApp, correo y calendario". */
export function whatsAppView(link: WhatsAppLink): WhatsAppView {
  switch (link.state) {
    case 'none':
      return { body: 'Te avisamos de lo importante y respondes desde aquí.', action: 'link', actionLabel: 'Vincular WhatsApp' };
    case 'pairing':
      return { badge: 'Vinculando', body: 'Escribe el código en tu WhatsApp para terminar.', action: 'open', actionLabel: 'Ver el código' };
    case 'linked':
      if (link.consentOutdated) {
        return {
          badge: 'En pausa',
          body: 'Cambiamos lo que hacemos con tu WhatsApp. Revísalo para seguir recibiendo avisos.',
          action: 'accept',
          actionLabel: 'Revisar',
        };
      }
      // What arrives is told in the Confío IA conversation and answered there: this row only manages the link.
      return {
        badge: 'Vinculado',
        body: 'Te aviso de lo importante en nuestra conversación, y ahí mismo respondes.',
        action: 'open',
        actionLabel: 'Ver vinculación',
      };
    case 'gone':
      return {
        badge: 'Desvinculado',
        body: link.reasonMessage || 'Tu WhatsApp se desvinculó. Puedes vincularlo otra vez.',
        action: 'link',
        actionLabel: 'Vincular otra vez',
      };
    case 'failed':
      return {
        badge: 'No se vinculó',
        body: link.reasonMessage || 'No se pudo vincular. Inténtalo de nuevo.',
        action: 'link',
        actionLabel: 'Intentar de nuevo',
      };
    default:
      return { body: 'Actualiza la app para ver esta opción.' };
  }
}


export const NOTICE_LABELS: Record<string, string> = {
  payment: 'Parece un cobro o un pago',
  order: 'Parece un pedido',
  delivery: 'Parece una entrega',
  appointment: 'Parece una cita',
  reply: 'Parece que esperan tu respuesta',
  urgent: 'Parece urgente',
};

/** "Revisado hace 12 min": when the chat list was last read, or nothing when it never was (or the clock is off). */
export function checkedAgo(iso: string | null, now: number): string | null {
  const at = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(at) || at > now + 60_000) {
    return null;
  }
  const minutes = Math.max(0, Math.floor((now - at) / 60_000));
  if (minutes < 1) {
    return 'Revisado ahora';
  }
  if (minutes < 60) {
    return `Revisado hace ${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `Revisado hace ${hours} h` : `Revisado hace ${Math.floor(hours / 24)} d`;
}

/** The first letter or digit of a chat's name, for its avatar; "#" when it has none (emoji only). */
export const initialOf = (name: string) => (name.match(/[\p{L}\p{N}]/u)?.[0] ?? '#').toUpperCase();

/** The 8 characters as WhatsApp takes them: "ABCD-EFGH" is copied as "ABCDEFGH". */
export const codeForCopy = (code: string) => code.replace(/[^A-Z0-9]/gi, '').toUpperCase();

export const PAIRING_STEPS = [
  'Abre WhatsApp → Dispositivos vinculados',
  'Vincular un dispositivo → «Vincular con el número de teléfono»',
  'Escribe el código',
];

/** What a draft card says about where it goes and how it went. */
export function draftView(draft: WhatsAppDraft): {
  heading: string; status?: string; canSend: boolean; done: boolean;
} {
  const to = draft.chat || draft.phone || 'tu chat';
  switch (draft.status) {
    case 'draft':
      return { heading: `Se enviará desde tu WhatsApp a ${to}:`, status: draft.reason ?? undefined, canSend: true, done: false };
    case 'sending':
      return { heading: `Enviando desde tu WhatsApp a ${to}:`, status: 'Enviando desde tu WhatsApp…', canSend: false, done: false };
    case 'sent':
      return { heading: `Enviado a ${to}:`, status: 'Enviado.', canSend: false, done: true };
    default:
      return {
        heading: `No sé si salió a ${to}:`,
        status: draft.reason || 'No sé si el mensaje salió. Revisa el chat en tu teléfono antes de repetirlo.',
        canSend: false,
        done: true,
      };
  }
}

/** The server forgets a message's text once it went: what was shown stays. A draft that vanished after it was
 * on its way is "no sé si salió"; one that vanished unsent (expired) is gone. */
export function mergeDraft(known: WhatsAppDraft | null, now: WhatsAppDraft | null): WhatsAppDraft | null {
  if (!now) {
    if (!known || known.status === 'draft') {
      return null;
    }
    return known.status === 'sent' ? known : { ...known, status: 'unknown', reason: null };
  }
  if (!known || known.id !== now.id) {
    return now;
  }
  return { ...now, chat: now.chat || known.chat, phone: now.phone || known.phone, body: now.body || known.body };
}

/** Poll while something is changing on the server. */
export const pollFor = (link: WhatsAppLink | null) => (link?.state === 'pairing' ? 2500 : 0);
