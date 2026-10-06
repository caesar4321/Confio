let mockResult: any = {};
jest.mock('@apollo/client', () => ({ useQuery: () => mockResult, gql: () => '' }));
jest.mock('../../apollo/queries', () => ({ GET_COMMUNITY_POSTING_STATUS: 'POSTING' }));

import { useCommunityComposeEntry } from '../useCommunityComposeEntry';

const status = (blockCode: string | null) => ({ data: { communityPostingStatus: { canPost: !blockCode, blockCode } } });

describe('useCommunityComposeEntry', () => {
  it('offers posting to verified and unverified people alike (the composer explains)', () => {
    mockResult = status(null);
    expect(useCommunityComposeEntry()).toBe(true);
    mockResult = status('not_verified');
    expect(useCommunityComposeEntry()).toBe(true);
  });

  it('hides only for the kill switch or a server without Comunidad', () => {
    mockResult = status('disabled');
    expect(useCommunityComposeEntry()).toBe(false);
    mockResult = { error: { message: "Cannot query field 'communityPostingStatus' on type 'Query'." } };
    expect(useCommunityComposeEntry()).toBe(false);
  });

  it('a passing network error keeps the entry; not-yet-answered does not show it', () => {
    mockResult = { error: { message: 'Network request failed' } };
    expect(useCommunityComposeEntry()).toBe(true);
    mockResult = {};
    expect(useCommunityComposeEntry()).toBe(false);
    expect(useCommunityComposeEntry(false)).toBe(false);
  });
});
