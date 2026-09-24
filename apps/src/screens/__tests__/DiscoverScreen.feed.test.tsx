import React from 'react';
import renderer, { act } from 'react-test-renderer';

type FeedState = { data?: any; loading: boolean; error?: any };

let mockFeed: FeedState;
let mockFeedFor: ((document: string) => FeedState) | null = null;
const mockDocuments: string[] = [];
const mockClientQuery = jest.fn();
const mockUpdateQuery = jest.fn();
const mockRefetch = jest.fn(() => Promise.resolve());
let mockFeedProps: any;
const mockLoadFailedHistory: boolean[] = [];

jest.mock('@apollo/client', () => ({
  NetworkStatus: { refetch: 4, ready: 7 },
  useMutation: () => [jest.fn()],
  useApolloClient: () => ({ query: mockClientQuery }),
  useQuery: (document: string) => {
    mockDocuments.push(document);
    return {
      ...(mockFeedFor ? mockFeedFor(document) : mockFeed),
      networkStatus: 7,
      refetch: mockRefetch,
      updateQuery: mockUpdateQuery,
    };
  },
}));
jest.mock('../../apollo/queries', () => ({
  GET_DISCOVER_FEED: 'LEGACY', GET_DISCOVER_FEED_SECTIONED: 'SECTIONED', GET_DISCOVER_FEED_CARDS: 'CARDS',
}));
jest.mock('../../apollo/mutations', () => ({ REACT_TO_MESSAGE_CONTENT: 'REACT' }));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: jest.fn() }),
  useFocusEffect: () => {},
}));
jest.mock('../../components/SkeletonLoader', () => ({ OfferCardSkeleton: 'OfferCardSkeleton' }));
jest.mock('../../components/DiscoverFeed', () => ({
  DISCOVER_SECTIONS: [
    { key: 'for_you', label: 'Para ti' },
    { key: 'official', label: 'Oficial' },
    { key: 'community', label: 'Comunidad' },
  ],
  DiscoverFeed: (props: any) => {
    mockFeedProps = props;
    mockLoadFailedHistory.push(props.loadFailed);
    return null;
  },
}));

import { DiscoverScreen } from '../DiscoverScreen';

const post = (id: number) => ({
  id: String(id), type: 'news', tag: '', tagColor: '#000', title: `Post ${id}`, body: '', time: '', thumbnail: false,
});
const page = (from: number, count: number, hasMore = true) => ({
  discoverFeed: { __typename: 'DiscoverFeedPageType', hasMore, items: Array.from({ length: count }, (_, i) => post(from + i)) },
});

const networkFailure = () => {
  const { ApolloError } = jest.requireActual('@apollo/client');
  return new ApolloError({ networkError: new Error('Network request failed') });
};

const render = () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => {
    tree = renderer.create(<DiscoverScreen />);
  });
  return tree;
};

describe('DiscoverScreen feed', () => {
  let resolvePage: (value: any) => void;

  beforeEach(() => {
    mockClientQuery.mockReset().mockImplementation(() => new Promise((resolve) => { resolvePage = resolve; }));
    mockUpdateQuery.mockReset();
    mockRefetch.mockClear();
    mockFeed = { data: page(1, 10), loading: false };
    mockFeedFor = null;
    mockDocuments.length = 0;
    mockLoadFailedHistory.length = 0;
  });

  it('steps down to the sectioned feed on a server without byline fields, without a failure flash', () => {
    const { ApolloError } = jest.requireActual('@apollo/client');
    const rejected = new ApolloError({
      networkError: Object.assign(new Error('Response not successful: Received status code 400'), {
        result: { errors: [{ message: 'Cannot query field "sourceAvatarUrl" on type "DiscoverFeedItemType".' }] },
      }),
    });
    mockFeedFor = (document) => (document === 'CARDS'
      ? { data: undefined, loading: false, error: rejected }
      : { data: page(1, 5, false), loading: false });
    render();
    expect(mockDocuments[0]).toBe('CARDS');
    expect(mockDocuments[mockDocuments.length - 1]).toBe('SECTIONED');
    // Every render along the way, including the one holding the rejection.
    expect(mockLoadFailedHistory.length).toBeGreaterThan(1);
    expect(mockLoadFailedHistory.every((failed) => failed === false)).toBe(true);
    expect(mockFeedProps.items).toHaveLength(5);
    expect(mockFeedProps.sections).toHaveLength(3);
  });

  it('drops a late page from an earlier visit to the same section', async () => {
    render();
    act(() => { mockFeedProps.onEndReached(); });
    expect(mockClientQuery.mock.calls[0][0].variables).toMatchObject({ offset: 10, section: 'official' });
    // Oficial → Comunidad → Oficial while page two is in flight.
    act(() => mockFeedProps.onSelectSection('community'));
    act(() => mockFeedProps.onSelectSection('official'));
    await act(async () => { resolvePage({ data: page(21, 10) }); });
    expect(mockUpdateQuery).not.toHaveBeenCalled();
  });

  it('appends a page that belongs to the list on screen', async () => {
    render();
    act(() => { mockFeedProps.onEndReached(); });
    await act(async () => { resolvePage({ data: page(11, 10, false) }); });
    const merged = mockUpdateQuery.mock.calls[0][0](page(1, 10));
    expect(merged.discoverFeed.items).toHaveLength(20);
    expect(merged.discoverFeed.hasMore).toBe(false);
  });

  it('does not page while the list is being replaced', () => {
    mockFeed = { data: page(1, 20), loading: true };
    render();
    act(() => { mockFeedProps.onEndReached(); });
    expect(mockClientQuery).not.toHaveBeenCalled();
  });

  it('shows the failure state when a refresh fails over an empty feed', () => {
    mockFeed = { data: page(1, 0, false), loading: false, error: networkFailure() };
    render();
    expect(mockFeedProps.loadFailed).toBe(true);
  });

  it('keeps showing posts when a refresh fails over a loaded feed', () => {
    mockFeed = { data: page(1, 3, false), loading: false, error: networkFailure() };
    render();
    expect(mockFeedProps.loadFailed).toBe(false);
    expect(mockFeedProps.items).toHaveLength(3);
  });
});
