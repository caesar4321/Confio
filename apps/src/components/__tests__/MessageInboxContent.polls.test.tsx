import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { InMemoryCache, gql } from '@apollo/client';
import { MockedProvider } from '@apollo/client/testing';
import { MessageInboxContent } from '../MessageInboxContent';
import { MessageInboxList } from '../MessageInboxList';
import { MessageChannelThread } from '../MessageChannelThread';
import { GET_MESSAGE_INBOX, GET_MESSAGE_CHANNEL_THREAD, GET_MESSAGE_INBOX_UNREAD_COUNT } from '../../apollo/queries';
import { MARK_MESSAGE_CHANNEL_SEEN, REACT_TO_MESSAGE_CONTENT } from '../../apollo/mutations';

let mockAccountId = 'account-1';
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true, isLoading: false, accountContextTick: 0 }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { id: mockAccountId } }) }));
jest.mock('../MessageInboxList', () => ({ MessageInboxList: () => null }));
jest.mock('../MessageChannelThread', () => ({ MessageChannelThread: () => null }));

const poll = {
  __typename: 'ContentPollType', id: '1', question: '¿Qué sigue?', closed: false, totalVotes: 0, viewerOptionId: null,
  options: [{ __typename: 'ContentPollOptionType', id: 'a', label: 'Pagos', count: 0 }, { __typename: 'ContentPollOptionType', id: 'b', label: 'Ahorro', count: 0 }],
};
const message = (id: number) => ({
  __typename: 'MessageThreadItemType', id: String(id), type: 'text', isPinned: false, occurredAt: '',
  tag: '', title: '', body: '', text: `Message ${id}`, time: 'Ahora', link: null, platforms: [], platformLinks: [],
  imageUrl: null, poll: id === 1 ? poll : null, reactionSummary: [], viewerReaction: null, canReact: true, senderType: null, senderName: null,
});
const channel = (messages: any[]) => ({
  __typename: 'MessageChannelType', id: 'julian', name: 'Julian', subtitle: '', preview: '', time: 'Ahora', unreadCount: 0, isMuted: false, messages,
});
const firstPage = Array.from({ length: 20 }, (_, index) => message(index + 1));
const inbox = (messages = firstPage) => ({ messageInbox: { __typename: 'MessageInboxType', totalUnreadCount: 0, channels: [channel(messages)] } });
const inboxMock = (data = inbox(), contextKey = 'account-1') => ({ request: { query: GET_MESSAGE_INBOX, variables: { contextKey } }, result: { data }, delay: 5, maxUsageCount: 10 });
const sharedMocks = (pageDelay = 0) => [
  { request: { query: MARK_MESSAGE_CHANNEL_SEEN, variables: { channelId: 'julian' } }, result: { data: { markMessageChannelSeen: { success: true, totalUnreadCount: 0 } } }, maxUsageCount: 3 },
  { request: { query: GET_MESSAGE_INBOX_UNREAD_COUNT, variables: { contextKey: 'account-1' } }, result: { data: { messageInboxUnreadCount: 0 } }, maxUsageCount: 3 },
  { request: { query: GET_MESSAGE_CHANNEL_THREAD, variables: { channelId: 'julian', offset: 20, limit: 20, contextKey: 'account-1' } }, delay: pageDelay, result: { data: { messageChannelThread: { __typename: 'MessageChannelThreadPageType', hasMore: false, channel: channel([message(21)]) } } } },
];
const flush = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)); }); };
async function mount(extraMocks: any[] = [], pageDelay = 0) {
  mockAccountId = 'account-1';
  const cache = new InMemoryCache({ typePolicies: { ContentPollOptionType: { keyFields: false }, MessageInboxType: { keyFields: false }, MessageChannelType: { keyFields: false }, MessageThreadItemType: { keyFields: false } } });
  const mocks = [inboxMock(), ...sharedMocks(pageDelay), ...extraMocks];
  let tree!: renderer.ReactTestRenderer;
  const element = () => <MockedProvider mocks={mocks} cache={cache}><MessageInboxContent /></MockedProvider>;
  act(() => { tree = renderer.create(element()); });
  await flush();
  const list = tree.root.findByType(MessageInboxList);
  act(() => list.props.onOpenChannel(list.props.channels[0]));
  await flush();
  return { tree, cache, element };
}
const thread = (tree: renderer.ReactTestRenderer) => tree.root.findByType(MessageChannelThread);
async function loadOlder(tree: renderer.ReactTestRenderer) {
  expect(thread(tree).props.hasMore).toBe(true);
  act(() => thread(tree).props.onLoadMore());
  await flush();
  expect(thread(tree).props.channel.messages).toHaveLength(21);
}

test('poll cache updates preserve loaded pages and a locally saved reaction', async () => {
  const { tree, cache } = await mount([{ request: { query: REACT_TO_MESSAGE_CONTENT, variables: { contentItemId: '1', emoji: '👍' } }, result: { data: { reactToMessageContent: { success: true, contentItemId: '1', viewerReaction: '👍', reactionSummary: [{ emoji: '👍', count: 1 }] } } } }]);
  await loadOlder(tree);
  await act(async () => thread(tree).props.onReact(1, '👍'));
  expect(thread(tree).props.channel.messages[0].viewerReaction).toBe('👍');
  act(() => { cache.writeFragment({ id: 'ContentPollType:1', fragment: gql`fragment VoteResult on ContentPollType { id question closed totalVotes viewerOptionId options { id label count } }`, data: { ...poll, totalVotes: 1, viewerOptionId: 'a', options: [{ ...poll.options[0], count: 1 }, poll.options[1]] } }); });
  await flush();
  expect(thread(tree).props.channel.messages).toHaveLength(21);
  expect(thread(tree).props.channel.messages[0].viewerReaction).toBe('👍');
  expect(thread(tree).props.hasMore).toBe(false);
  act(() => tree.unmount());
});

test('explicit refresh with identical first-page data discards stale older pages and restores pagination', async () => {
  const { tree } = await mount([inboxMock()]);
  await loadOlder(tree);
  expect(thread(tree).props.hasMore).toBe(false);
  await act(async () => thread(tree).props.onRefresh());
  await flush();
  expect(thread(tree).props.channel.messages).toHaveLength(20);
  expect(thread(tree).props.hasMore).toBe(true);
  act(() => tree.unmount());
});

test('account context switch clears the previous thread and loads the new inbox', async () => {
  const { tree, element } = await mount([inboxMock(inbox([message(99)]), 'account-2')]);
  await loadOlder(tree);
  mockAccountId = 'account-2';
  act(() => tree.update(element()));
  expect(tree.root.findAllByType(MessageChannelThread)).toHaveLength(0);
  await flush();
  expect(tree.root.findByType(MessageInboxList).props.channels[0].messages.map((entry: any) => entry.id)).toEqual([99]);
  act(() => tree.unmount());
});


test('a late pagination response cannot append the previous account messages after switching', async () => {
  const { tree, element } = await mount([inboxMock(inbox([message(99)]), 'account-2')], 150);
  act(() => thread(tree).props.onLoadMore());
  mockAccountId = 'account-2';
  act(() => tree.update(element()));
  await flush();
  expect(tree.root.findByType(MessageInboxList).props.channels[0].messages.map((entry: any) => entry.id)).toEqual([99]);
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 175)); });
  expect(tree.root.findByType(MessageInboxList).props.channels[0].messages.map((entry: any) => entry.id)).toEqual([99]);
  act(() => tree.unmount());
});
