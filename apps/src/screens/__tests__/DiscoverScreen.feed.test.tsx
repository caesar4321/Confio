import React from 'react';
import renderer, { act } from 'react-test-renderer';

type FeedState = { data?: any; loading: boolean; error?: any };

let mockFeed: FeedState;
const mockFetchMore = jest.fn();
const mockRefetch = jest.fn(() => Promise.resolve());
let mockFeedProps: any;

jest.mock('@apollo/client', () => ({
  NetworkStatus: { refetch: 4, ready: 7 },
  useMutation: () => [jest.fn()],
  useQuery: (document: string, options: { skip?: boolean }) => {
    if (document === 'LEGACY' && options?.skip) return { data: undefined, loading: false };
    return {
      ...mockFeed,
      networkStatus: 7,
      refetch: mockRefetch,
      fetchMore: mockFetchMore,
    };
  },
}));
jest.mock('../../apollo/queries', () => ({ GET_DISCOVER_FEED: 'LEGACY', GET_DISCOVER_FEED_SECTIONED: 'SECTIONED' }));
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
  beforeEach(() => {
    mockFetchMore.mockReset().mockResolvedValue(undefined);
    mockRefetch.mockClear();
    mockFeed = { data: page(1, 10), loading: false };
  });

  it('drops a late page from an earlier visit to the same section', async () => {
    render();
    await act(async () => { mockFeedProps.onEndReached(); });
    const { updateQuery } = mockFetchMore.mock.calls[0][0];
    // Oficial → Comunidad → Oficial while page two is in flight.
    act(() => mockFeedProps.onSelectSection('community'));
    act(() => mockFeedProps.onSelectSection('official'));
    const previous = page(1, 10);
    expect(updateQuery(previous, { fetchMoreResult: page(21, 10) })).toBe(previous);
  });

  it('appends a page that belongs to the list on screen', async () => {
    render();
    await act(async () => { mockFeedProps.onEndReached(); });
    const { updateQuery } = mockFetchMore.mock.calls[0][0];
    const merged = updateQuery(page(1, 10), { fetchMoreResult: page(11, 10, false) });
    expect(merged.discoverFeed.items).toHaveLength(20);
    expect(merged.discoverFeed.hasMore).toBe(false);
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
