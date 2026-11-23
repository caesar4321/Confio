import { agentTaskNotificationRoute, forgetCards, latestCardFor, showCard, taskActions, taskIdOf } from '../helpers';

const ID = '3f2b8c1e-9a4d-4e6f-8b2a-1c3d5e7f9a0b';

it('takes only a purchase id, never anything else in its place', () => {
  expect(taskIdOf(ID)).toBe(ID);
  expect(taskIdOf(` ${ID.toUpperCase()} `)).toBe(ID);
  for (const bad of ['', 'payment_intent', `${ID}/../x`, 42, null, undefined]) {
    expect(taskIdOf(bad)).toBeNull();
  }
});

it('knows a purchase notification, from a push (flattened data_ keys) or the in-app list', () => {
  expect(agentTaskNotificationRoute({ data_type: 'agent_task', data_task_id: ID })).toBe(ID);
  expect(agentTaskNotificationRoute({ type: 'agent_task', task_id: ID })).toBe(ID);
  expect(agentTaskNotificationRoute(JSON.stringify({ type: 'agent_task', task_id: ID }))).toBe(ID);
  expect(agentTaskNotificationRoute({ data_type: 'smart_account', data_task_id: ID })).toBeNull();
  expect(agentTaskNotificationRoute({ data_type: 'agent_task', data_task_id: 'nope' })).toBeNull();
  expect(agentTaskNotificationRoute('not json')).toBeNull();
});

it('finds the purchases a message carries, once each', () => {
  expect(taskActions([
    { type: 'task', target: ID }, { type: 'task', target: ID }, { type: 'task', target: 'not-an-id' },
    { type: 'navigate', target: ID },
  ])).toEqual([ID]);
});

it('a purchase is drawn once: under the newest message that carries it', () => {
  forgetCards();
  const first = showCard(ID, 'm1', 100);
  expect(latestCardFor(ID)).toBe('m1');
  const second = showCard(ID, 'm2', 200);
  expect(latestCardFor(ID)).toBe('m2');
  second();   // the newest note scrolled out of the list: the card does not jump to an older note
  first();
  expect(latestCardFor(ID)).toBe('m2');
});
