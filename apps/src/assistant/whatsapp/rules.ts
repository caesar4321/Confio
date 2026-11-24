// What the WhatsApp screens say, decided here so it can be tested without a screen. Copy is written here,
// never by the model: a model's summary is shown as a claim ("Parece…"), never as fact.
import type { WhatsAppDraft, WhatsAppLink } from './api';

/** What anyone reads before linking: three lines and the one risk, in plain words. */
export const CONSENT_POINTS: { icon: string; text: string }[] = [
  { icon: 'bell', text: 'Te avisamos de cobros, pedidos y citas.' },
  { icon: 'check-circle', text: 'Respondes desde aquí. Nada sale sin tu OK.' },
  { icon: 'eye-off', text: 'No marcamos tus chats como leídos (solo el que respondes).' },
];
/** Always in sight before linking: what is read, by whom, for how long, and what contacts may see. */
export const CONSENT_DATA = 'Cada ~2 horas y al abrir Confío IA leemos el nombre y la última línea de tus chats sin '
  + 'leer. Una IA marca lo importante y lo guardamos cifrado mientras siga vinculado. Tus contactos pueden verte «en '
  + 'línea» un momento. '
  + 'Al vincularlo te dejamos una nota en tu propio chat, para que sepas que se vinculó.';

/** A number with its country code, as WhatsApp takes it: + and 8 to 15 digits. */
export const validPhone = (value: string) => /^\+\d{8,15}$/.test(value.replace(/[\s\-().]/g, ''));
export const CONSENT_RISK = 'WhatsApp no permite oficialmente apps como esta y podría restringir tu cuenta.';

/** The whole text the person accepts, behind "Cómo funciona". Version WHATSAPP_CONSENT_VERSION in api.ts:
 * change both together. */
export function consentText(): string[] {
  return [
    'Escribes tu número de WhatsApp y WhatsApp te pide confirmarlo con un código en tu teléfono. Confío lo '
      + 'vincula como un dispositivo más, en un navegador en la nube que es solo tuyo. Lo verás en WhatsApp como '
      + '«Chrome» en Dispositivos vinculados.',
    'Al vincularlo, Confío escribe una sola nota en tu chat contigo mismo («Mensaje para ti») diciendo que se '
      + 'vinculó: si alguien te pidió el código con engaños, lo ves ahí. Es el único mensaje que Confío escribe sin '
      + 'que lo apruebes.',
    'Cada unas dos horas, y cuando abres Confío IA, miramos tu lista de chats: el nombre y la última línea de '
      + 'los chats sin leer. No abrimos tus chats para eso, así que no marcamos nada como leído (al enviar una '
      + 'respuesta, ese chat sí queda leído). No guardamos grupos ni mensajes que parezcan códigos o contraseñas.',
    'Un modelo de IA marca lo importante (cobros, pedidos, entregas, citas, alguien esperando tu respuesta) y '
      + 'te avisamos. Guardamos eso cifrado mientras tu WhatsApp siga vinculado; al desvincularlo, desde Confío o desde '
      + 'tu teléfono, lo borramos.',
    'Solo enviamos un mensaje cuando tú lo apruebas aquí, uno por uno y escrito a ritmo de persona. Nunca '
      + 'pagamos nada desde WhatsApp.',
    'Cuando miramos tu lista, tus contactos pueden verte «en línea» un momento. WhatsApp no permite oficialmente '
      + 'clientes como este y podría restringir una cuenta; cuidamos tu número enviando poco y solo lo que '
      + 'apruebas, pero el riesgo no es cero.',
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
      return {
        badge: 'Vinculado',
        body: link.notices.length
          ? `${counted(link.notices.length)} por revisar.`
          : 'Te avisamos cuando llegue algo importante.',
        action: 'open',
        actionLabel: 'Abrir WhatsApp en Confío',
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
        body: link.reasonMessage || 'No se pudo vincular. Inténtalo de nuevo.',
        action: 'link',
        actionLabel: 'Intentar de nuevo',
      };
    default:
      return { body: 'Actualiza la app para ver esta opción.' };
  }
}

const counted = (count: number) => (count === 1 ? '1 mensaje importante' : `${count > 9 ? 'Más de 9' : count} mensajes importantes`);

export const NOTICE_LABELS: Record<string, string> = {
  payment: 'Parece un cobro o un pago',
  order: 'Parece un pedido',
  delivery: 'Parece una entrega',
  appointment: 'Parece una cita',
  reply: 'Parece que esperan tu respuesta',
  urgent: 'Parece urgente',
};

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
