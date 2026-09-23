import { ApolloError } from '@apollo/client';
import { isSchemaMismatch } from '../graphqlSchemaMismatch';

const http400 = (message: string) => new ApolloError({
  networkError: Object.assign(new Error('Response not successful: Received status code 400'), {
    result: { errors: [{ message }] },
  }),
});

describe('isSchemaMismatch', () => {
  it('reads a validation failure from the HTTP 400 body', () => {
    expect(isSchemaMismatch(http400('Unknown argument "section" on field "Query.discoverFeed".'))).toBe(true);
    expect(isSchemaMismatch(http400('Cannot query field "isOfficial" on type "DiscoverFeedItemType".'))).toBe(true);
  });

  it('accepts a caller-named older-server rejection', () => {
    const error = new ApolloError({ graphQLErrors: [{ message: 'Unknown Discover section' } as any] });
    expect(isSchemaMismatch(error)).toBe(false);
    expect(isSchemaMismatch(error, /Unknown Discover section/i)).toBe(true);
  });

  it('never treats an outage as an older server', () => {
    expect(isSchemaMismatch(undefined)).toBe(false);
    expect(isSchemaMismatch(new ApolloError({ networkError: new Error('Network request failed') }))).toBe(false);
    expect(isSchemaMismatch(new ApolloError({ graphQLErrors: [{ message: 'Internal server error' } as any] }))).toBe(false);
  });
});
