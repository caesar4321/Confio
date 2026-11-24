import type { WhatsAppDraft, WhatsAppLink } from '../api';
import { codeForCopy, consentText, draftView, pollFor, whatsAppView } from '../rules';
import { checkedAgo, initialOf } from '../rules';

const link = (over: Partial<WhatsAppLink> = {}): WhatsAppLink => ({
  state: 'none', code: null, codeAt: null, phoneHint: null, reason: null, reasonMessage: null, linkedAt: null,
  lastSyncAt: null, ownPhoneHint: '4567', suggestedPhone: null, consentVersion: 3, consentOutdated: false, notices: [], ...over,
});
const draft = (over: Partial<WhatsAppDraft> = {}): WhatsAppDraft => ({
  id: 'd1', chat: 'Farmacia Central', phone: null, body: 'Hola', status: 'draft', reason: null, displayHash: 'h', ...over,
});

it('anyone can link, by typing a number with its country code', () => {
  expect(whatsAppView(link()).action).toBe('link');
  expect(whatsAppView(link({ ownPhoneHint: null })).action).toBe('link');
  const { validPhone } = require('../rules');
  expect(validPhone('+591 7123 4567')).toBe(true);
  expect(validPhone('71234567')).toBe(false);  // no country code: another country's number to WhatsApp
  expect(validPhone('+12')).toBe(false);
});

it('every state says what to do next', () => {
  expect(whatsAppView(link({ state: 'pairing' })).action).toBe('open');
  expect(whatsAppView(link({ state: 'linked', consentOutdated: true })).action).toBe('accept');
  expect(whatsAppView(link({ state: 'gone', reasonMessage: 'Se desvinculó.' })).body).toBe('Se desvinculó.');
  expect(whatsAppView(link({ state: 'failed' })).actionLabel).toBe('Intentar de nuevo');
  expect(whatsAppView(link({ state: 'linked', notices: Array(12).fill({}) })).body).toContain('nuestra conversación');
});

it('the consent says the risks plainly', () => {
  const text = consentText().join(' ');
  for (const words of ['no marcamos nada como leído', 'mientras tu WhatsApp siga vinculado', 'tú lo apruebas', 'en línea', 'restringir', 'desvincularlo',
    'Mensaje para ti', 'único mensaje que Confío escribe sin']) {
    expect(text).toContain(words);
  }
});

it('a draft is sendable only as a draft, and an unknown result is never "sent"', () => {
  expect(draftView(draft()).canSend).toBe(true);
  expect(draftView(draft({ status: 'sending' })).canSend).toBe(false);
  expect(draftView(draft({ status: 'sent' })).status).toBe('Enviado.');
  const unknown = draftView(draft({ status: 'unknown', reason: null }));
  expect(unknown.status).toContain('No sé si el mensaje salió');
  expect(unknown.canSend).toBe(false);
  expect(draftView(draft({ chat: null, phone: '+584141234567' })).heading).toBe('Se enviará desde tu WhatsApp a +584141234567:');
  expect(draftView(draft({ status: 'sent' })).heading).toBe('Enviado a Farmacia Central:');
  expect(draftView(draft({ status: 'unknown', chat: null })).heading).toBe('No sé si salió a tu chat:');
});

it('the code is copied as WhatsApp takes it, and polled only while it is up', () => {
  expect(codeForCopy('abcd-efgh')).toBe('ABCDEFGH');
  expect(pollFor(link({ state: 'pairing' }))).toBeGreaterThan(0);
  expect(pollFor(link({ state: 'linked' }))).toBe(0);
  expect(pollFor(null)).toBe(0);
});

it('checkedAgo: minutes, hours, days, and nothing for a missing or future time', () => {
  const now = Date.parse('2026-11-24T12:00:00Z');
  expect(checkedAgo(null, now)).toBeNull();
  expect(checkedAgo('2026-11-24T13:00:00Z', now)).toBeNull();
  expect(checkedAgo('2026-11-24T11:59:40Z', now)).toBe('Revisado ahora');
  expect(checkedAgo('2026-11-24T11:48:00Z', now)).toBe('Revisado hace 12 min');
  expect(checkedAgo('2026-11-24T09:00:00Z', now)).toBe('Revisado hace 3 h');
  expect(checkedAgo('2026-11-22T12:00:00Z', now)).toBe('Revisado hace 2 d');
});

it('initialOf: first letter or digit, "#" for emoji-only names', () => {
  expect(initialOf('farmacia Central')).toBe('F');
  expect(initialOf('🍕 Pizzería')).toBe('P');
  expect(initialOf('🎉')).toBe('#');
  expect(initialOf('+591 7123')).toBe('5');
});
