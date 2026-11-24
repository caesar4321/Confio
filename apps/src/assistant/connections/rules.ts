// What to show, decided here so it can be tested without a screen.
import type { Connections } from './api';
import type { WhatsAppLink } from '../whatsapp/api';

/** WhatsApp is offered to whoever has not linked it (they type their number), and again to whoever WhatsApp
 * unlinked (a phone unused for a while, "Chrome" removed). */
export const offersWhatsApp = (link: WhatsAppLink | null) => link?.state === 'none' || link?.state === 'gone';

export const WHATSAPP_RELINK_CARD = {
  title: 'Tu WhatsApp se desvinculó',
  body: 'WhatsApp lo desvincula si tu teléfono pasa un tiempo sin usarse. Vincúlalo otra vez para seguir recibiendo avisos.',
  cta: 'Vincular otra vez',
};

export const WHATSAPP_CARD = {
  title: 'Vincula tu WhatsApp',
  body: 'Te avisamos de cobros, pedidos y citas, y respondes desde aquí.',
  cta: 'Ver cómo funciona',
};

export const SNOOZE_DAYS = 14;

/** What this build can really open. */
export type Build = { mail: boolean; calendar: boolean };
export type GmailView = { body: string; badge?: string; action?: 'open' | 'ask' };

export function gmailView(data: Connections, build: Build): GmailView {
  const account = data.googleEmail;
  switch (data.gmail) {
    case 'invited':
      return build.mail
        ? {
            badge: 'Tienes cupo',
            body: account
              ? `Al conectar elige ${account}. Durante la prueba Google rechaza las demás cuentas.`
              : 'Al conectar elige el Gmail que agregamos a la prueba. Google rechaza las demás cuentas.',
            action: 'open',
          }
        : { badge: 'Tienes cupo', body: 'Actualiza la app para conectar tu Gmail.' };
    case 'connected':
      return build.mail
        ? { badge: 'Conectado', body: 'Tu asistente te avisa de lo que debes atender.', action: 'open' }
        : { badge: 'Conectado', body: 'Actualiza la app para ver tu correo aquí.' };
    case 'reconnect':
      return build.mail
        ? { badge: 'Reconectar', body: 'Durante la prueba Google pide reconectar cada 7 días.', action: 'open' }
        : { badge: 'Reconectar', body: 'Actualiza la app para reconectar tu Gmail.' };
    case 'paused':
      return {
        badge: 'En pausa',
        body: 'La prueba está en pausa para ti: no estamos leyendo tu correo. Puedes desconectarlo cuando quieras.',
        action: build.mail ? 'open' : undefined,
      };
    case 'waiting':
      return {
        badge: 'En la lista',
        body: account ? `Te avisamos si puedes conectar ${account}.` : 'Te avisamos si puedes conectarlo.',
      };
    case 'waiting_full':
      return {
        badge: 'En la lista',
        body: 'Los cupos de la prueba están completos. Te avisamos si lo abrimos a más personas.',
      };
    case 'full':
      return {
        badge: 'Cupos completos',
        body: 'La prueba ya está completa. ¿Te avisamos si lo abrimos a más personas?',
        action: 'ask',
      };
    case 'request':
      return { badge: 'En prueba', body: 'Lo estamos probando con pocas personas. ¿Quieres un cupo?', action: 'ask' };
    case 'left':
      return { body: 'Saliste de la prueba. ¿Te avisamos si puedes volver?', action: 'ask' };
    case 'soon':
      return { badge: 'Próximamente', body: '¿Te avisamos si puedes conectarlo?', action: 'ask' };
    default:
      // A newer server's state.
      return { body: 'Actualiza la app para ver esta opción.' };
  }
}

/** The card's words, true in every state that gets a card (promptKind). */
export function cardText(data: Connections): { title: string; body: string; cta: string } {
  const benefit = 'te avisa de facturas, vencimientos y viajes que llegan a tu correo.';
  switch (data.gmail) {
    case 'invited':
      return { title: 'Ya tienes tu cupo de Gmail', body: `Conéctalo y tu asistente ${benefit}`, cta: 'Conectar' };
    case 'reconnect':
      return { title: 'Vuelve a conectar tu Gmail', body: 'La conexión venció y no te estamos avisando.', cta: 'Reconectar' };
    case 'request':
      return { title: 'Estamos probando Gmail', body: `Pide un cupo: tu asistente ${benefit}`, cta: 'Ver cómo funciona' };
    case 'full':
      return {
        title: 'Gmail en tu asistente: cupos completos',
        body: 'La prueba está completa. Puedes pedir que te avisemos si lo abrimos a más personas.',
        cta: 'Ver correo y calendario',
      };
    default:
      return {
        title: 'Próximamente: tu correo y tu calendario',
        body: 'Para que tu asistente te avise de facturas y viajes antes de que se te pasen.',
        cta: 'Ver correo y calendario',
      };
  }
}

/** The card, the small chip that always stays, or nothing. */
export function promptKind(input: {
  data: Connections | null;
  /** The opening. Mid-chat it is never more than the chip: they came for something else. */
  starters: boolean;
  build: Build;
  snoozedUntil: number;
  now: number;
  /** WhatsApp can be linked now and is not (offersWhatsApp). */
  whatsApp?: boolean;
}): 'card' | 'chip' | null {
  const { data, build, starters, snoozedUntil, now, whatsApp = false } = input;
  if (!data) {
    return null;
  }
  if (!starters) {
    return 'chip';
  }
  // Something waits on them: "Ahora no" doesn't hide it.
  if (build.mail && (data.gmail === 'invited' || data.gmail === 'reconnect')) {
    return 'card';
  }
  // Their answer and their "Ahora no" hold.
  // `whatsApp` already holds WhatsApp's own "Ahora no"; the mail one never hides it.
  return whatsApp || (unanswered(data) && snoozedUntil <= now) ? 'card' : 'chip';
}

/** The only case where "Ahora no" matters, so the only one that reads the keystore. */
export const unanswered = (data: Connections) =>
  !data.gmailAnswered && ['soon', 'request', 'full'].includes(data.gmail);

const START = '(?:^|[^a-záéíóúñê])';
const END = '(?![a-záéíóúñê])';
const ASK = '(?:lee[rs]?|leas|revis[a-záéíóú]*|mira[rs]?|busca[rs]?|conect[a-záéíóú]*|vincul[a-záéíóú]*|integr[a-záéíóú]*'
  + '|sincroniz[a-záéíóú]*|acced[a-záéíóú]*|resum[a-záéíóú]*|organiz[a-záéíóú]*|chec[a-záéíóú]*|chequ?e[a-záéíóú]*'
  + '|ver|veas|tengo|tienes|hay|lê|ler)';
const THING = '(?:whats ?app|wsp|gmail|correos?|e-?mails?|mails?|bandeja|inbox|calendarios?|google calendar|citas|eventos|reuniones)';
const INTENT = new RegExp(
  `${START}${ASK}\\s+(?:(?:a|al|con|de|en|el|la|los|las|mi|mis|tu|meu|meus|últimos)\\s+){0,3}${THING}${END}`
  + `|${START}mis (?:citas|eventos|reuniones) (?:de|para) (?:hoy|mañana|esta semana)${END}`,
  'i',
);
// About money, safety or the account itself, or a no: not the moment to offer it.
const OTHER_MATTER = new RegExp(
  `${START}(?:c[óo]digo|clave|contraseña|frase|cambi[a-záéíóú]*|fals[oa]s?|estaf[a-záéíóú]*|phishing|hack[a-záéíóú]*`
  + '|rob[a-záéíóú]*|perd[ií][a-záéíóú]*|sospech[a-záéíóú]*|rar[oa]s?|recuper[a-záéíóú]*|verific[a-záéíóú]*'
  + '|comprobante|dep[óo]sito|retiro|recarga|billetera|no (?:puedo|quiero|conectes|leas|revises))'
  + END,
  'i',
);

/** They asked, in their last message, to read or connect mail or calendar. */
export function mentionsConnections(messages: { role: string; body: string }[]): boolean {
  const recent = messages.slice(-2);
  for (let index = recent.length - 1; index >= 0; index -= 1) {
    if (recent[index].role === 'user') {
      const said = recent[index].body.slice(0, 300);
      // An address is someone to pay, or their own data: not a wish to connect.
      return !said.includes('@') && !OTHER_MATTER.test(said) && INTENT.test(said);
    }
  }
  return false;
}
