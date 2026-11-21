// SDL additions with their fallbacks for an older server, the account
// switcher's smart merge (as useAccountManager runs it), and notification
// routing for Cuenta inteligente.
import { indexInherited, mergeSmartAccounts } from '../smartAccounts';
import { smartNotificationRoute } from '../smartAccountNotificationRoute';
import type { StoredAccount } from '../accountManager';

jest.mock('react-native-keychain', () => ({}));

const entry = (id: string, at: string, accountIndex?: number) => ({
  inheritedAccountId: id, contractAddress: '0x' + id.padStart(40, '0'), fromName: `De ${id}`,
  inheritedAt: at, ...(accountIndex === undefined ? {} : { accountIndex }),
});

describe('InheritedAccount.accountIndex', () => {
  it('uses the server index when every entry has a distinct one', () => {
    const out = indexInherited([entry('a', '2026-01-01T00:00:00Z', 2), entry('b', '2026-02-01T00:00:00Z', 1)]);
    expect(out.map((x) => [x.entry.inheritedAccountId, x.index])).toEqual([['b', 1], ['a', 2]]);
  });

  it('falls back to the order received on an older server', () => {
    const out = indexInherited([entry('a', '2026-03-01T00:00:00Z'), entry('b', '2026-02-01T00:00:00Z')]);
    expect(out.map((x) => [x.entry.inheritedAccountId, x.index])).toEqual([['b', 1], ['a', 2]]);
  });

  it('never mixes the two (a partial or duplicate answer falls back entirely)', () => {
    expect(indexInherited([entry('a', '2026-03-01T00:00:00Z', 5), entry('b', '2026-02-01T00:00:00Z')])
      .map((x) => x.index)).toEqual([1, 2]);
    expect(indexInherited([entry('a', '2026-03-01T00:00:00Z', 1), entry('b', '2026-02-01T00:00:00Z', 1)])
      .map((x) => x.entry.inheritedAccountId)).toEqual(['b', 'a']);
  });
});

describe('useAccountManager smart merge', () => {
  const own = { status: 'active', contractAddress: '0x' + 'aa'.repeat(20) };
  const prev: StoredAccount[] = mergeSmartAccounts([], { ok: true, data: own }, {
    ok: true, data: [entry('a', '2026-01-01T00:00:00Z', 3)],
  });

  it('builds own (smart_0) and inherited (server index) entries', () => {
    expect(prev.map((a) => a.id)).toEqual(['smart_0', 'smart_3']);
    expect(prev[1].smart).toMatchObject({ inherited: true, inheritedAccountId: 'a' });
  });

  it('keeps the previous half when only that read failed', () => {
    const next = mergeSmartAccounts(prev, { ok: false }, { ok: true, data: [] });
    expect(next.map((a) => a.id)).toEqual(['smart_0']);
    const next2 = mergeSmartAccounts(prev, { ok: true, data: null }, { ok: false });
    expect(next2.map((a) => a.id)).toEqual(['smart_3']);
  });

  it('keeps everything when both reads failed', () => {
    expect(mergeSmartAccounts(prev, { ok: false }, { ok: false })).toEqual(prev);
  });

  it('drops an own account that is not open', () => {
    const next = mergeSmartAccounts(prev, { ok: true, data: { status: 'none', contractAddress: null } }, { ok: false });
    expect(next.map((a) => a.id)).toEqual(['smart_3']);
  });
});

describe('notification routes', () => {
  it('reads `route` and the server\'s `screen`, in the list and flattened in a push', () => {
    expect(smartNotificationRoute({ route: 'SmartAccountBilling' })).toEqual({ screen: 'SmartAccountBilling' });
    expect(smartNotificationRoute({ screen: 'SmartAccountRules' })).toEqual({ screen: 'SmartAccountRules' });
    expect(smartNotificationRoute({ data_screen: 'BeneficiaryStatus' })).toEqual({ screen: 'BeneficiaryStatus' });
    expect(smartNotificationRoute(JSON.stringify({ route: 'SmartAccountHome' }))).toEqual({ screen: 'SmartAccountHome' });
  });

  it('carries the opaque ids the screens need', () => {
    expect(smartNotificationRoute({ data_screen: 'BeneficiaryInvite', data_designationId: 'd9' }))
      .toEqual({ screen: 'BeneficiaryInvite', params: { designationId: 'd9' } });
    expect(smartNotificationRoute({ route: 'BeneficiaryClaimStatus', designationId: 'd1' }))
      .toEqual({ screen: 'BeneficiaryClaimStatus', params: { designationId: 'd1' } });
    expect(smartNotificationRoute({ route: 'InheritedAccount', inheritedAccountId: 'i1' }))
      .toEqual({ screen: 'InheritedAccount', params: { inheritedAccountId: 'i1' } });
    expect(smartNotificationRoute({ route: 'InheritedAccount' })).toEqual({ screen: 'InheritedAccount' });
  });

  it('opens Inicio (whose row resolves the designation) when a designation screen lacks its id', () => {
    expect(smartNotificationRoute({ route: 'BeneficiaryInvite' }))
      .toEqual({ screen: 'BottomTabs', params: { screen: 'Home' } });
  });

  it('ignores anything else', () => {
    expect(smartNotificationRoute({ screen: 'Home' })).toBeNull();
    expect(smartNotificationRoute({ route: 'Verification' })).toBeNull();
    expect(smartNotificationRoute(null)).toBeNull();
    expect(smartNotificationRoute('{bad')).toBeNull();
    expect(smartNotificationRoute({ action_url: 'confio://smart-account' })).toBeNull();
  });
});
