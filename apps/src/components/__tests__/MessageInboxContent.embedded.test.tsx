import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { InMemoryCache, useQuery } from '@apollo/client';
import { MockedProvider } from '@apollo/client/testing';
import { MessageInboxContent } from '../MessageInboxContent';
import { MessageChannelThread } from '../MessageChannelThread';
import { GET_MESSAGE_INBOX, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../../apollo/queries';
import { MARK_MESSAGE_CHANNEL_SEEN } from '../../apollo/mutations';

jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, isLoading: false, accountContextTick: 0 }) }));
let mockAccount: any = { id: 'account-1' };
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: mockAccount }) }));
jest.mock('../../assistant/AssistantContext', () => ({ useOptionalAssistant: () => null }));
jest.mock('../MessageInboxList', () => ({ MessageInboxList: () => null }));
jest.mock('../MessageChannelThread', () => ({ MessageChannelThread: () => null }));

const message = (id: number) => ({
  __typename: 'MessageThreadItemType', id: String(id), type: 'text', isPinned: false, occurredAt: '',
  tag: '', title: '', body: '', text: `Message ${id}`, time: 'Ahora', link: null, platforms: [], platformLinks: [],
  imageUrl: null, poll: null, reactionSummary: [], viewerReaction: null, canReact: true, senderType: null, senderName: null,
});
const channel = (id: string) => ({
  __typename: 'MessageChannelType', id, name: id, subtitle: '', preview: '', time: 'Ahora', unreadCount: 1, isMuted: false, messages: [message(1)],
});
const inbox = () => ({ messageInbox: { __typename: 'MessageInboxType', totalUnreadCount: 2, channels: [channel('julian'), channel('confio-news')] } });
const mocks = () => [
  { request: { query: GET_MESSAGE_INBOX, variables: { contextKey: 'no-account' } }, result: { data: inbox() }, delay: 5, maxUsageCount: 10 },
  { request: { query: GET_MESSAGE_INBOX_UNREAD_COUNT, variables: { contextKey: 'no-account' } }, result: { data: { messageInboxUnreadCount: 0 } }, maxUsageCount: 6 },
  { request: { query: GET_MESSAGE_INBOX, variables: { contextKey: 'account-1' } }, result: { data: inbox() }, delay: 5, maxUsageCount: 10 },
  { request: { query: MARK_MESSAGE_CHANNEL_SEEN, variables: { channelId: 'julian' } }, result: { data: { markMessageChannelSeen: { success: true, totalUnreadCount: 0 } } }, maxUsageCount: 3 },
  { request: { query: MARK_MESSAGE_CHANNEL_SEEN, variables: { channelId: 'confio-news' } }, result: { data: { markMessageChannelSeen: { success: true, totalUnreadCount: 0 } } }, maxUsageCount: 3 },
  { request: { query: GET_MESSAGE_INBOX_UNREAD_COUNT, variables: { contextKey: 'account-1' } }, result: { data: { messageInboxUnreadCount: 0 } }, maxUsageCount: 6 },
];
const newCache = () => new InMemoryCache({ typePolicies: { MessageInboxType: { keyFields: false }, MessageChannelType: { keyFields: false }, MessageThreadItemType: { keyFields: false } } });
const flush = async (ms = 50) => { await act(async () => { await new Promise(resolve => setTimeout(resolve, ms)); }); };

// The sheet's own copy of the inbox query (unread dots on the chat heads).
function Sheet({ channel }: { channel?: 'julian' | 'confio' }) {
  useQuery(GET_MESSAGE_INBOX, { variables: { contextKey: 'account-1' }, fetchPolicy: 'cache-and-network', errorPolicy: 'ignore' });
  return channel ? <MessageInboxContent embeddedChannelId={channel} /> : null;
}

test('A: embedded alone opens the thread', async () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MockedProvider mocks={mocks()} cache={newCache()}><MessageInboxContent embeddedChannelId="julian" /></MockedProvider>); });
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  act(() => tree.unmount());
});

test('B: embedded mounted together with the sheet query (push: opens straight on a channel)', async () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MockedProvider mocks={mocks()} cache={newCache()}><Sheet channel="julian" /></MockedProvider>); });
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  act(() => tree.unmount());
});

test('C: sheet query first, then head tapped', async () => {
  let tree!: renderer.ReactTestRenderer;
  const cache = newCache(); const m = mocks();
  act(() => { tree = renderer.create(<MockedProvider mocks={m} cache={cache}><Sheet /></MockedProvider>); });
  await flush();
  act(() => tree.update(<MockedProvider mocks={m} cache={cache}><Sheet channel="julian" /></MockedProvider>));
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  act(() => tree.unmount());
});

test('D: sheet query in flight, embedded mounts a moment later', async () => {
  let tree!: renderer.ReactTestRenderer;
  const cache = newCache(); const m = mocks();
  act(() => { tree = renderer.create(<MockedProvider mocks={m} cache={cache}><Sheet /></MockedProvider>); });
  await flush(1);
  act(() => tree.update(<MockedProvider mocks={m} cache={cache}><Sheet channel="julian" /></MockedProvider>));
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  act(() => tree.unmount());
});

afterEach(() => { mockAccount = { id: 'account-1' }; });

test('E: account context settles after the thread opened (push-driven launch)', async () => {
  mockAccount = null;
  let tree!: renderer.ReactTestRenderer;
  const cache = newCache(); const m = mocks();
  const el = () => <MockedProvider mocks={m} cache={cache}><MessageInboxContent embeddedChannelId="julian" /></MockedProvider>;
  act(() => { tree = renderer.create(el()); });
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  mockAccount = { id: 'account-1' };
  act(() => tree.update(el()));
  await flush();
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(1);
  expect(tree.root.findByType(MessageChannelThread).props.channel.id).toBe('julian');
  act(() => tree.unmount());
});
