// The 2026-11-20 SDL additions, each read in its own document, and what the
// client does when an older server lacks them.
const mockQuery = jest.fn();
const mockMutate = jest.fn();
jest.mock('../../apollo/client', () => ({
  apolloClient: { query: (...a: any[]) => mockQuery(...a), mutate: (...a: any[]) => mockMutate(...a) },
}));

import {
  INHERITED_ACCOUNTS, INHERITED_ACCOUNT_INDEXES, SMART_ACCOUNT, SMART_ACCOUNT_OFFER,
  fetchBeneficiaryRiskDisclosure, fetchInheritedAccounts, fetchSmartAccountBeneficiaryEnabled,
  prepareBeneficiaryWindowChange,
} from '../smartAccount';
import { print } from 'graphql';

const inherited = (id: string) => ({
  inheritedAccountId: id, contractAddress: '0x' + 'bb'.repeat(20), fromName: 'Luis', inheritedAt: '2026-11-15T12:00:00Z',
  totalUsd: '1.00', assets: [], canMoveToSmartAccount: false,
});
// Graphene answers an unknown field with HTTP 400; Apollo surfaces it like this.
const schemaError = (field: string) => Object.assign(new Error(`Cannot query field "${field}"`), { graphQLErrors: [] });

beforeEach(() => jest.clearAllMocks());

describe('isolation', () => {
  it('keeps the frozen documents free of the new fields', () => {
    expect(print(INHERITED_ACCOUNTS)).not.toContain('accountIndex');
    expect(print(SMART_ACCOUNT)).not.toContain('beneficiaryEnabled');
    expect(print(SMART_ACCOUNT_OFFER)).not.toContain('beneficiaryRiskDisclosure');
    expect(print(INHERITED_ACCOUNT_INDEXES)).toContain('accountIndex');
  });
});

describe('InheritedAccount.accountIndex', () => {
  it('merges the index read into the list', async () => {
    mockQuery.mockImplementation(async ({ query }: any) => (query === INHERITED_ACCOUNT_INDEXES
      ? { data: { inheritedAccounts: [{ inheritedAccountId: 'i1', accountIndex: 2 }] } }
      : { data: { inheritedAccounts: [inherited('i1')] } }));
    const out = await fetchInheritedAccounts();
    expect(out).toEqual({ ok: true, data: [{ ...inherited('i1'), accountIndex: 2 }] });
  });

  it('still lists the accounts, without an index, on an older server', async () => {
    mockQuery.mockImplementation(async ({ query }: any) => {
      if (query === INHERITED_ACCOUNT_INDEXES) {
        throw schemaError('accountIndex');
      }
      return { data: { inheritedAccounts: [inherited('i1')] } };
    });
    const out = await fetchInheritedAccounts();
    expect(out).toEqual({ ok: true, data: [inherited('i1')] });
  });

  it('ignores an invalid index', async () => {
    mockQuery.mockImplementation(async ({ query }: any) => (query === INHERITED_ACCOUNT_INDEXES
      ? { data: { inheritedAccounts: [{ inheritedAccountId: 'i1', accountIndex: 0 }] } }
      : { data: { inheritedAccounts: [inherited('i1')] } }));
    expect(await fetchInheritedAccounts()).toEqual({ ok: true, data: [inherited('i1')] });
  });

  it('reports a failed list as failed, not empty', async () => {
    mockQuery.mockRejectedValue(new Error('network'));
    expect(await fetchInheritedAccounts()).toEqual({ ok: false });
  });
});

describe('SmartAccount.beneficiaryEnabled', () => {
  it('answers the flag, or null without an account', async () => {
    mockQuery.mockResolvedValueOnce({ data: { smartAccount: { beneficiaryEnabled: true } } });
    expect(await fetchSmartAccountBeneficiaryEnabled()).toEqual({ ok: true, data: true });
    mockQuery.mockResolvedValueOnce({ data: { smartAccount: null } });
    expect(await fetchSmartAccountBeneficiaryEnabled()).toEqual({ ok: true, data: null });
  });

  it('fails only itself on an older server (the screen then uses the offer)', async () => {
    mockQuery.mockRejectedValueOnce(schemaError('beneficiaryEnabled'));
    expect(await fetchSmartAccountBeneficiaryEnabled()).toEqual({ ok: false });
  });
});

describe('SmartAccountOffer.beneficiaryRiskDisclosure', () => {
  it('returns the server sentences, dropping blanks', async () => {
    mockQuery.mockResolvedValueOnce({ data: { smartAccountOffer: { beneficiaryRiskDisclosure: ['Uno {name}.', ' ', 'Dos {days}.'] } } });
    expect(await fetchBeneficiaryRiskDisclosure()).toEqual({ ok: true, data: ['Uno {name}.', 'Dos {days}.'] });
  });

  it('fails on an older server', async () => {
    mockQuery.mockRejectedValueOnce(schemaError('beneficiaryRiskDisclosure'));
    expect(await fetchBeneficiaryRiskDisclosure()).toEqual({ ok: false });
  });
});

describe('prepareBeneficiaryWindowChange', () => {
  it('sends only the window (no account id) and returns the batch', async () => {
    const batch = { success: true, errorCode: null, errorMessage: null, requestId: 'r', calls: [], notAfter: null, summary: ['x'] };
    mockMutate.mockResolvedValueOnce({ data: { prepareBeneficiaryWindowChange: batch } });
    expect(await prepareBeneficiaryWindowChange(365)).toEqual(batch);
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ windowDays: 365 });
  });

  it('says "not available" rather than "check your connection" on an older server', async () => {
    mockMutate.mockRejectedValueOnce(schemaError('prepareBeneficiaryWindowChange'));
    const out = await prepareBeneficiaryWindowChange(90);
    expect(out.success).toBe(false);
    expect(out.errorCode).toBe('unsupported');
    expect(out.errorMessage).toContain('todavía no está disponible');
  });

  it('keeps "network" for a real network failure', async () => {
    mockMutate.mockRejectedValueOnce(new Error('Network request failed'));
    expect((await prepareBeneficiaryWindowChange(90)).errorCode).toBe('network');
  });
});
