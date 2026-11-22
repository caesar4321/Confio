import React from 'react';
import { act, create } from 'react-test-renderer';

import ConnectionsPrompt from '../ConnectionsPrompt';
import { readSnooze } from '../store';
import { useConnections } from '../useConnections';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../components/common/AppText', () => ({ Text: require('react-native').Text }));
jest.mock('../store', () => ({
  useKnownSnooze: () => undefined, readSnooze: jest.fn(async () => 0), openConnections: jest.fn(), snooze: jest.fn(),
}));
jest.mock('../useConnections', () => ({
  useViewer: () => '1',
  useConnections: jest.fn(() => ({ connections: null, build: { mail: false, calendar: false }, refetch: jest.fn() })),
}));

const render = async (element: React.ReactElement) => {
  await act(async () => {
    create(element);
  });
};
beforeEach(() => jest.clearAllMocks());

it('an ordinary turn asks the server and the keystore nothing', async () => {
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'manda 20 a Juan' }]} />);
  await render(<ConnectionsPrompt where="box" starters={false} />);
  expect(useConnections).not.toHaveBeenCalled();
  expect(readSnooze).not.toHaveBeenCalled();
});

it('switched off: the opening never touches the keystore', async () => {
  await render(<ConnectionsPrompt where="box" starters />);
  expect(readSnooze).not.toHaveBeenCalled();
});

it('asked mid-chat: from the cache first', async () => {
  await render(<ConnectionsPrompt where="box" starters={false} messages={[{ role: 'user', body: 'lee mi correo' }]} />);
  expect(useConnections).toHaveBeenCalledWith('1', 'cache-first');
});
