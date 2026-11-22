import type { Connections, GmailState } from '../api';
import { cardText, gmailView, mentionsConnections, promptKind } from '../rules';

jest.mock('@apollo/client', () => ({ gql: () => ({}) }));

const data = (gmail: GmailState, more: Partial<Connections> = {}): Connections => ({
  gmail, gmailAnswered: false, googleEmail: null, suggestedEmail: null, calendar: 'soon', calendarAnswered: false, ...more,
});
const ON = { mail: true, calendar: false };
const OFF = { mail: false, calendar: false };
const kind = (d: Connections | null, more: object = {}) =>
  promptKind({ data: d, build: ON, starters: true, snoozedUntil: 0, now: 10, ...more });

describe('discovery', () => {
  it('shows nothing without the server', () => expect(kind(null)).toBeNull());
  it.each(['soon', 'request', 'full'] as const)('%s: a card until answered', (state) => {
    expect(kind(data(state))).toBe('card');
    expect(kind(data(state, { gmailAnswered: true }))).toBe('chip');
  });
  it('"Ahora no" leaves the chip', () => expect(kind(data('soon'), { snoozedUntil: 11 })).toBe('chip'));
  it('an invitation beats "Ahora no"', () => expect(kind(data('invited'), { snoozedUntil: 11 })).toBe('card'));
  it('an invitation this build cannot open is not a card', () =>
    expect(kind(data('invited'), { build: OFF })).toBe('chip'));
  it('never a card for someone connected or in the list', () => {
    for (const state of ['connected', 'paused', 'waiting', 'waiting_full'] as const) {
      expect(kind(data(state))).toBe('chip');
    }
  });
  it('mid-chat never more than the chip', () => {
    expect(kind(data('soon'), { starters: false })).toBe('chip');
    expect(kind(data('invited'), { starters: false })).toBe('chip');
  });
  it('full is never headlined as coming soon', () => {
    expect(cardText(data('full')).title).not.toContain('Próximamente');
    expect(cardText(data('invited')).title).toContain('cupo');
  });
});

describe('what each state says', () => {
  const all: GmailState[] = ['soon', 'request', 'full', 'left', 'waiting', 'waiting_full', 'invited', 'connected', 'reconnect', 'paused'];
  it.each(all)('%s never sells a place or blames money', (state) => {
    const text = JSON.stringify([gmailView(data(state), ON), cardText(data(state))]);
    expect(text).not.toMatch(/compra|precio|US\$|CASA|suscr|plan /i);
  });
  it('full asks to be told', () => expect(gmailView(data('full'), ON)).toMatchObject({ badge: 'Cupos completos', action: 'ask' }));
  it('names the account Google accepts', () =>
    expect(gmailView(data('invited', { googleEmail: 'a@gmail.com' }), ON).body).toContain('a@gmail.com'));
  it('an old build says to update', () => {
    const view = gmailView(data('invited'), OFF);
    expect(view.action).toBeUndefined();
    expect(view.body).toContain('Actualiza');
  });
  it('a newer server state is not a dead screen', () =>
    expect(gmailView(data('later' as GmailState), ON).body).toContain('Actualiza'));
});

describe('mentions', () => {
  const said = (body: string) => mentionsConnections([{ role: 'user', body }, { role: 'assistant', body: 'ok' }]);
  it.each(['¿puedes leer mi correo?', 'revisa Gmail', 'qué tengo en mi calendario', 'mis citas de hoy', 'lê meus e-mails', 'revisa mis mails', 'conecta el correo electrónico',
    '¿qué hay en mi bandeja?'])(
    'yes: %s', (body) => expect(said(body)).toBe(true));
  it.each([
    'manda 20 a Juan', 'quiero ver mi agenda de contactos', 'cómo va el bitcoin', 'cambiar de gmailero',
    'manda 20 a juan@gmail.com', 'Mi Zelle es ana@gmail.com', 'no me llega el código a mi correo',
    'cambiar mi correo de la cuenta', 'me llegó un email falso de Confío pidiendo mi clave',
    'revisa si llegó el código a mi correo', 'quiero ver mi saldo',
    'me robaron el celular y no puedo acceder a mi correo', 'perdí el acceso, no puedo ver mi correo',
    'no puedo ver el correo con mi frase de recuperación', 'revisa mi correo, te mandé el comprobante del depósito',
    'revisa el correo de verificación de mi identidad', 'tengo eventos raros en mi billetera', 'no quiero conectar mi correo',
  ])(
    'no: %s', (body) => expect(said(body)).toBe(false));
  it('the assistant saying it does not count', () =>
    expect(mentionsConnections([{ role: 'assistant', body: 'tu Gmail' }])).toBe(false));
});
