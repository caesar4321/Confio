jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/AppText', () => ({ Text: require('react-native').Text }));

import { agentTaskNotificationRoute, allowedInLiveView, allowedSubframe, pastesInChat, taskIdOf, timeLeft }
  from '../helpers';
import { taskActions } from '../TaskChips';

const ID = '3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b';

it('takes only a task id, never anything else in its place', () => {
  expect(taskIdOf(ID)).toBe(ID);
  expect(taskIdOf(` ${ID.toUpperCase()} `)).toBe(ID);
  for (const bad of ['', 'payment_intent', `${ID}/../x`, 42, null, undefined]) {
    expect(taskIdOf(bad)).toBeNull();
  }
});

it('opens the task from its push (flattened data_ keys) or the in-app list, and nothing else', () => {
  expect(agentTaskNotificationRoute({ data_type: 'agent_task', data_task_id: ID, data_screen: 'AssistantThread' }))
    .toBe(ID);
  expect(agentTaskNotificationRoute({ type: 'agent_task', task_id: ID })).toBe(ID);
  expect(agentTaskNotificationRoute(JSON.stringify({ type: 'agent_task', task_id: ID }))).toBe(ID);
  expect(agentTaskNotificationRoute({ data_type: 'smart_account', data_task_id: ID })).toBeNull();
  expect(agentTaskNotificationRoute({ data_type: 'agent_task', data_task_id: 'nope' })).toBeNull();
  expect(agentTaskNotificationRoute('not json')).toBeNull();
  expect(agentTaskNotificationRoute(undefined)).toBeNull();
});

it('lets the live view load only on its own host, over https', () => {
  const host = 'www.browserbase.com';
  expect(allowedInLiveView('https://www.browserbase.com/devtools-fullscreen/inspector.html?wss=x', host)).toBe(true);
  expect(allowedInLiveView('https://WWW.browserbase.com', host)).toBe(true);
  expect(allowedInLiveView('https://www.browserbase.com:443/x', host)).toBe(true);
  expect(allowedInLiveView('about:blank', host)).toBe(true);
  for (const url of [
    'http://www.browserbase.com/x', 'https://www.browserbase.com.evil.test/', 'https://www.browserbase.com@evil.test/',
    'https://evil.test/?u=https://www.browserbase.com', 'https://www.browserbase.com:8443/x', 'javascript:alert(1)',
    'intent://x#Intent;end', 'file:///etc/hosts',
  ]) {
    expect(allowedInLiveView(url, host)).toBe(false);
  }
  expect(allowedInLiveView('https://www.browserbase.com/', null)).toBe(false);
});

it('counts down to the deadline and says nothing once it passed', () => {
  const now = Date.parse('2026-11-23T12:00:00Z');
  expect(timeLeft('2026-11-23T12:14:05Z', now)).toBe('14:05');
  expect(timeLeft('2026-11-23T12:00:09Z', now)).toBe('0:09');
  expect(timeLeft('2026-11-23T11:59:00Z', now)).toBeNull();
  expect(timeLeft(null, now)).toBeNull();
  expect(timeLeft('soon', now)).toBeNull();
});

it('draws one chip per purchase note, always in its own words', () => {
  expect(taskActions([
    { type: 'task', target: ID, label: 'Ver la tarea' },
    { type: 'task', target: ID, label: 'otra vez' },
    { type: 'task', target: 'not-an-id' },
    { type: 'navigate', target: ID },
  ])).toEqual([{ taskId: ID, label: 'Abrir la tienda' }]);
  expect(taskActions([{ type: 'task', target: ID }])).toEqual([{ taskId: ID, label: 'Abrir la tienda' }]);
});

it('sends only a Brazilian store\'s unread code to the chat', () => {
  for (const reason of ['code', 'code_refused', 'screen', 'retry', 'offsite', 'unsigned']) {
    expect(pastesInChat('mercadolivre.com.br', reason)).toBe(true);
    expect(pastesInChat('mercadolibre.com.mx', reason)).toBe(false);
    expect(pastesInChat('tienda.com.bo', reason)).toBe(false);
  }
  expect(pastesInChat('mercadolivre.com.br', 'checkout')).toBe(false);
  expect(pastesInChat('brasil.com.mx', 'code')).toBe(false);
});

it('lets frames inside the live view load https only', () => {
  expect(allowedSubframe('https://x.test/a')).toBe(true);
  expect(allowedSubframe('about:blank')).toBe(true);
  for (const url of ['http://x.test/', 'tel:1', 'intent://x', 'https://', 'javascript:1']) {
    expect(allowedSubframe(url)).toBe(false);
  }
});
