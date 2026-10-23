import { DirectMessage, chatTime, mergeMessages, previewOf } from '../directMessages';

const msg = (over: Partial<DirectMessage>): DirectMessage => ({
  id: '1', body: 'hola', kind: 'text', fromMe: false, status: 'approved', createdAt: '2026-10-23T10:00:00Z', ...over,
});

test('the server copy replaces the local one with the same key, newest first', () => {
  const local = msg({ id: 'local-k1', fromMe: true, status: 'sending', clientKey: 'k1' });
  const merged = mergeMessages([local, msg({ id: '5' })], [msg({ id: '7', fromMe: true, status: 'pending', clientKey: 'k1' })]);
  expect(merged.map((m) => m.id)).toEqual(['7', '5']);
});

test('a later status for the same id wins and nothing repeats', () => {
  const merged = mergeMessages([msg({ id: '7', status: 'pending' })], [msg({ id: '7', status: 'approved' }), msg({ id: '3' })]);
  expect(merged.map((m) => [m.id, m.status])).toEqual([['7', 'approved'], ['3', 'approved']]);
});

test('an unsent local message stays on top until the server has it', () => {
  const unsent = msg({ id: 'local-k2', fromMe: true, status: 'unsent', clientKey: 'k2' });
  expect(mergeMessages([unsent], [msg({ id: '9' })]).map((m) => m.id)).toEqual(['local-k2', '9']);
});

test('inbox previews', () => {
  expect(previewOf(msg({ fromMe: true, status: 'pending' }))).toBe('Tú: revisando…');
  expect(previewOf(msg({ fromMe: true, status: 'rejected' }))).toBe('Tú: no enviado');
  expect(previewOf(msg({ fromMe: true }))).toBe('Tú: hola');
  expect(previewOf(msg({ kind: 'tip' }))).toBe('Te envió una propina');
  expect(previewOf(null)).toBe('');
});

test('chat times', () => {
  const now = new Date(2026, 9, 23, 18, 0);
  expect(chatTime(new Date(2026, 9, 23, 9, 5).toISOString(), now)).toBe('09:05');
  expect(chatTime(new Date(2026, 9, 22, 9, 5).toISOString(), now)).toBe('ayer');
  expect(chatTime(new Date(2026, 9, 12, 9, 5).toISOString(), now)).toBe('12 oct');
  expect(chatTime('nope', now)).toBe('');
});

test('a late pending copy never undoes a verdict', () => {
  const merged = mergeMessages([msg({ id: '8', fromMe: true, status: 'rejected', reason: 'no' })],
    [msg({ id: '8', fromMe: true, status: 'pending' })]);
  expect(merged[0].status).toBe('rejected');
});
