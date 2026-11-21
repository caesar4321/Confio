jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(async () => false),
  setGenericPassword: jest.fn(async () => true),
  resetGenericPassword: jest.fn(async () => true),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AFTER_FIRST_UNLOCK' },
}));
import Keychain from 'react-native-keychain';
import { AccountManager, requireKeyedAccountType } from '../accountManager';
import {
  buildSmartStoredAccounts, orderInherited, smartPlaceholderAccount, smartSwitcherLabel,
} from '../smartAccounts';

const manager = AccountManager.getInstance();

describe('smart account ids', () => {
  it('parses the own account and inherited ones', () => {
    expect(manager.parseAccountId('smart_0')).toEqual({ type: 'smart', index: 0 });
    expect(manager.parseAccountId('smart_2')).toEqual({ type: 'smart', index: 2 });
  });

  it('still parses personal and business ids', () => {
    expect(manager.parseAccountId('personal_0')).toEqual({ type: 'personal', index: 0 });
    expect(manager.parseAccountId('business_19_0')).toEqual({ type: 'business', index: 0, businessId: '19' });
  });

  it('rejects malformed smart ids', () => {
    expect(() => manager.parseAccountId('smart_')).toThrow();
    expect(() => manager.parseAccountId('smart_x')).toThrow();
    expect(() => manager.parseAccountId('smart_1_2')).toThrow();
  });

  it('round-trips a context to its id', () => {
    expect(manager.contextToAccountId({ type: 'smart', index: 1 })).toBe('smart_1');
    expect(manager.contextToAccountId({ type: 'business', index: 0, businessId: '7' })).toBe('business_7_0');
    expect(manager.contextToAccountId({ type: 'personal', index: 0 })).toBe('personal_0');
  });

  it('stores a smart context under its id', async () => {
    await manager.setActiveAccountContext({ type: 'smart', index: 0 });
    expect((Keychain.setGenericPassword as jest.Mock).mock.calls.pop()[1]).toBe('smart_0');
    expect(await manager.getActiveAccountContext()).toEqual({ type: 'smart', index: 0 });
    await manager.setActiveAccountContext({ type: 'personal', index: 0 });
  });
});

describe('a smart context has no key of its own', () => {
  it('signs with personal_0, own or inherited', () => {
    expect(manager.getSigningContext({ type: 'smart', index: 0 })).toEqual({ type: 'personal', index: 0 });
    expect(manager.getSigningContext({ type: 'smart', index: 3 })).toEqual({ type: 'personal', index: 0 });
  });

  it('leaves keyed contexts as they are', () => {
    expect(manager.getSigningContext({ type: 'business', index: 0, businessId: '7' }))
      .toEqual({ type: 'business', index: 0, businessId: '7' });
  });

  it('refuses to derive anything for a smart type', () => {
    expect(() => requireKeyedAccountType('smart')).toThrow();
    expect(requireKeyedAccountType('personal')).toBe('personal');
    expect(requireKeyedAccountType('business')).toBe('business');
  });

  it('never allocates a local index for one', async () => {
    await expect(manager.getNextAvailableIndex('smart')).rejects.toThrow();
  });

  it('tells own from inherited', () => {
    expect(manager.isSmartContext({ type: 'smart' })).toBe(true);
    expect(manager.isSmartContext({ type: 'personal' })).toBe(false);
    expect(manager.isInheritedSmartContext({ type: 'smart', index: 0 })).toBe(false);
    expect(manager.isInheritedSmartContext({ type: 'smart', index: 1 })).toBe(true);
  });
});

describe('switcher entries', () => {
  const inheritedA = { inheritedAccountId: 'a', contractAddress: '0xa', fromName: 'Ana', inheritedAt: '2026-03-01T00:00:00Z' };
  const inheritedB = { inheritedAccountId: 'b', contractAddress: '0xb', fromName: 'Luis', inheritedAt: '2026-01-01T00:00:00Z' };

  it('lists the own account as smart_0 with the server address', () => {
    const [own] = buildSmartStoredAccounts({ status: 'active', contractAddress: '0xc' }, []);
    expect(own).toMatchObject({ id: 'smart_0', type: 'smart', index: 0, name: 'Cuenta inteligente' });
    expect(own.smart).toEqual({ inherited: false, contractAddress: '0xc' });
    expect(own.algorandAddress).toBe('');
  });

  it('lists no own account when there is none', () => {
    expect(buildSmartStoredAccounts({ status: 'none', contractAddress: null }, [])).toEqual([]);
    expect(buildSmartStoredAccounts(null, [])).toEqual([]);
  });

  it('keeps a cancel-pending or expired account listed', () => {
    expect(buildSmartStoredAccounts({ status: 'cancel_pending', contractAddress: '0xc' }, [])).toHaveLength(1);
    expect(buildSmartStoredAccounts({ status: 'expired', contractAddress: '0xc' }, [])).toHaveLength(1);
  });

  it('numbers inherited accounts in the order received, from 1', () => {
    const list = buildSmartStoredAccounts(null, [inheritedA, inheritedB]);
    expect(list.map((a) => [a.id, a.smart?.inheritedAccountId])).toEqual([['smart_1', 'b'], ['smart_2', 'a']]);
    expect(list[0].name).toBe('Cuenta de Luis');
    expect(orderInherited([inheritedA, inheritedB]).map((a) => a.inheritedAccountId)).toEqual(['b', 'a']);
  });

  it('labels an inherited entry "heredada"', () => {
    const [own, got] = buildSmartStoredAccounts({ status: 'active', contractAddress: '0xc' }, [inheritedA]);
    expect(smartSwitcherLabel(own)).not.toContain('heredada');
    expect(smartSwitcherLabel(got)).toContain('heredada');
  });

  it('has a placeholder for a smart context before the server answers', () => {
    expect(smartPlaceholderAccount({ type: 'smart', index: 0 })).toMatchObject({ id: 'smart_0', type: 'smart' });
    expect(smartPlaceholderAccount({ type: 'smart', index: 2 })).toMatchObject({ id: 'smart_2', smart: { inherited: true } });
  });
});
