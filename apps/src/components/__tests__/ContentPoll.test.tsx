import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Animated, Pressable } from 'react-native';
import { InMemoryCache, gql } from '@apollo/client';
import { MockedProvider } from '@apollo/client/testing';
import { ContentPoll } from '../ContentPoll';
import { VOTE_ON_CONTENT_POLL } from '../../apollo/mutations';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');

test('unmounting a poll stops its in-progress result animations', () => {
  const animations: Array<{ start: jest.Mock; stop: jest.Mock; reset: jest.Mock }> = [];
  const timing = jest.spyOn(Animated, 'timing').mockImplementation(() => {
    const animation = { start: jest.fn(), stop: jest.fn(), reset: jest.fn() };
    animations.push(animation);
    return animation;
  });
  try {
    const { tree } = mount(voted);
    act(() => tree.unmount());
    expect(animations).toHaveLength(2);
    expect(animations.every(animation => animation.stop.mock.calls.length === 1)).toBe(true);
  } finally {
    timing.mockRestore();
  }
});

const fragment = gql`fragment TestPoll on ContentPollType {
  id question closed totalVotes viewerOptionId options { id label count }
}`;
const poll = {
  __typename: 'ContentPollType', id: '42', question: '¿Qué sigue?', closed: false,
  totalVotes: 0, viewerOptionId: null,
  options: [
    { __typename: 'ContentPollOptionType', id: 'a', label: 'Pagos', count: 0 },
    { __typename: 'ContentPollOptionType', id: 'b', label: 'Ahorro', count: 0 },
  ],
};
const voted = { ...poll, totalVotes: 1, viewerOptionId: 'a', options: [{ ...poll.options[0], count: 1 }, poll.options[1]] };
const flush = async () => { await act(async () => { await new Promise(resolve => setTimeout(resolve, 40)); }); };

function mount(value = poll, mocks: any[] = [], copies = 1) {
  const cache = new InMemoryCache({ typePolicies: { ContentPollOptionType: { keyFields: false } } });
  cache.writeFragment({ id: `ContentPollType:${value.id}`, fragment, data: value });
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MockedProvider cache={cache} mocks={mocks}>
    <>{Array.from({ length: copies }, (_, i) => <ContentPoll key={i} poll={value} />)}</>
  </MockedProvider>); });
  return { tree, cache };
}

test('a vote updates both surfaces without mixing options from other polls', async () => {
  const response = jest.fn(() => ({ data: { voteOnContentPoll: { __typename: 'VoteOnContentPoll', success: true, poll: voted } } }));
  const { tree, cache } = mount(poll, [{ request: { query: VOTE_ON_CONTENT_POLL, variables: { contentItemId: '42', optionId: 'a' } }, result: response }], 2);
  cache.writeFragment({ id: 'ContentPollType:99', fragment, data: { ...poll, id: '99', options: [{ ...poll.options[0], label: 'Otra encuesta' }, poll.options[1]] } });
  act(() => {
    const button = tree.root.findAllByType(Pressable)[0];
    button.props.onPress();
    button.props.onPress();
  });
  await flush();
  expect(response).toHaveBeenCalledTimes(1);
  const buttons = tree.root.findAllByType(Pressable);
  expect(buttons[0].props.accessibilityState.checked).toBe(true);
  expect(buttons[2].props.accessibilityState.checked).toBe(true);
  expect(JSON.stringify(tree.toJSON())).toContain('100%');
  expect(JSON.stringify(tree.toJSON())).not.toContain('Otra encuesta');
  act(() => tree.unmount());
});

test('closed polls disable all answer options', () => {
  const { tree } = mount({ ...poll, closed: true });
  expect(tree.root.findAllByType(Pressable).every(button => button.props.disabled)).toBe(true);
  expect(JSON.stringify(tree.toJSON())).toContain('Encuesta cerrada');
  act(() => tree.unmount());
});

test('failed vote shows a retry message and leaves selection unchanged', async () => {
  const { tree } = mount(poll, [{ request: { query: VOTE_ON_CONTENT_POLL, variables: { contentItemId: '42', optionId: 'a' } }, error: new Error('offline') }]);
  act(() => { tree.root.findAllByType(Pressable)[0].props.onPress(); });
  await flush();
  expect(JSON.stringify(tree.toJSON())).toContain('No se pudo guardar tu voto');
  expect(tree.root.findAllByType(Pressable)[0].props.accessibilityState.checked).toBe(false);
  act(() => tree.unmount());
});


test('an error on one poll does not carry over when the displayed publication changes', async () => {
  const mocks = [{ request: { query: VOTE_ON_CONTENT_POLL, variables: { contentItemId: '42', optionId: 'a' } }, error: new Error('offline') }];
  const { tree, cache } = mount(poll, mocks);
  act(() => { tree.root.findAllByType(Pressable)[0].props.onPress(); });
  await flush();
  expect(JSON.stringify(tree.toJSON())).toContain('No se pudo guardar tu voto');
  const nextPoll = { ...poll, id: '43', question: 'Nueva pregunta' };
  cache.writeFragment({ id: 'ContentPollType:43', fragment, data: nextPoll });
  act(() => tree.update(<MockedProvider cache={cache} mocks={mocks}><><ContentPoll key={0} poll={nextPoll} /></></MockedProvider>));
  expect(JSON.stringify(tree.toJSON())).toContain('Nueva pregunta');
  expect(JSON.stringify(tree.toJSON())).not.toContain('No se pudo guardar tu voto');
  act(() => tree.unmount());
});

test('results stay hidden until the viewer votes', () => {
  const { tree } = mount({ ...poll, totalVotes: 3, options: [{ ...poll.options[0], count: 2 }, { ...poll.options[1], count: 1 }] });
  const json = JSON.stringify(tree.toJSON());
  expect(json).not.toContain('67%');
  expect(json).toContain('Vota para ver los resultados');
  expect(tree.root.findAllByType(Pressable)[0].props.accessibilityLabel).toBe('Pagos');
  act(() => tree.unmount());
});
