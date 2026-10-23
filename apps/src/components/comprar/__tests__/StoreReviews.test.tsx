import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../../contexts/CountryContext', () => ({ useCountry: () => ({ userCountry: null }) }));
const mockReviews = { current: [] as any[] };
const mockError = { current: undefined as any };
jest.mock('@apollo/client', () => ({
  gql: () => ({}),
  useQuery: () => ({ data: mockError.current ? undefined : { marketplaceStoreReviews: mockReviews.current }, error: mockError.current, loading: false, refetch: jest.fn(() => Promise.resolve()), fetchMore: jest.fn() }),
}));

import { StoreReviews } from '../StoreReviews';

const text = (tree: renderer.ReactTestRenderer) => JSON.stringify(tree.toJSON());

it('shows each rating, its text only when published, and who wrote it by username', () => {
  mockReviews.current = [
    { id: '1', rating: 5, comment: 'Hermosa chompa, llegó al día.', author: 'ana_q', productTitle: 'Chompa', createdAt: '2026-10-20T12:00:00Z' },
    { id: '2', rating: 2, comment: null, author: 'luis', productTitle: 'Gorro', createdAt: '2026-10-21T12:00:00Z' },
  ];
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StoreReviews storeId="1" avgRating="3.5" ratingCount={2} />); });
  expect(text(tree)).toContain('Hermosa chompa, llegó al día.');
  expect(text(tree)).toContain('ana_q');
  expect(tree.root.findAll((n) => n.props.testID === 'review-2').length).toBeGreaterThan(0);
});

it('in preview, links to all reviews when there are more', () => {
  mockReviews.current = [{ id: '1', rating: 4, comment: null, author: 'a', productTitle: 'X', createdAt: '2026-10-20T12:00:00Z' }];
  const onSeeAll = jest.fn();
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StoreReviews storeId="1" avgRating={4} ratingCount={7} preview={2} onSeeAll={onSeeAll} />); });
  const link = tree.root.findAll((n) => n.props.accessibilityRole === 'button' && typeof n.props.onPress === 'function')[0];
  act(() => { link.props.onPress(); });
  expect(onSeeAll).toHaveBeenCalled();
});

it('says where reviews come from when there are none', () => {
  mockReviews.current = [];
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StoreReviews storeId="1" ratingCount={0} />); });
  expect(text(tree)).toContain('Aún no hay opiniones');
});


it('a failed load offers a retry instead of claiming there are no reviews', () => {
  mockError.current = new Error('network');
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StoreReviews storeId="1" ratingCount={3} />); });
  expect(JSON.stringify(tree.toJSON())).not.toContain('Aún no hay opiniones');
  expect(tree.root.findAll((n) => n.props.testID === 'reviews-retry').length).toBeGreaterThan(0);
  mockError.current = undefined;
});
