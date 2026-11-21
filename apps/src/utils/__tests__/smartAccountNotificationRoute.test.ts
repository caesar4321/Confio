// A Cuenta inteligente notification tapped from a business context (owner or
// employee) switches to the person first: personal_0, or the inherited
// account's smart_N when this session knows it.
import { smartNotificationSwitchTarget } from '../smartAccountNotificationRoute';
import { rememberKnownSmartAccounts, buildSmartStoredAccounts } from '../smartAccounts';

const business = { type: 'business', index: 0, businessId: '19' };

afterEach(() => rememberKnownSmartAccounts([]));

describe('smartNotificationSwitchTarget', () => {
  it('switches to personal_0 from a business context', () => {
    expect(smartNotificationSwitchTarget({ route: 'SmartAccountBilling' }, business)).toBe('personal_0');
    expect(smartNotificationSwitchTarget(
      JSON.stringify({ screen: 'BeneficiaryInvite', designationId: 'd1' }), business,
    )).toBe('personal_0');
  });

  it('does not switch from a personal or smart context', () => {
    expect(smartNotificationSwitchTarget({ route: 'SmartAccountBilling' }, { type: 'personal' })).toBeNull();
    expect(smartNotificationSwitchTarget({ route: 'SmartAccountBilling' }, { type: 'smart' })).toBeNull();
  });

  it('ignores notifications that are not Cuenta inteligente ones', () => {
    expect(smartNotificationSwitchTarget({ notification_type: 'SEND_RECEIVED' }, business)).toBeNull();
  });

  it('opens a known inherited account in its own smart_N', () => {
    rememberKnownSmartAccounts(buildSmartStoredAccounts(null, [
      { inheritedAccountId: 'i1', contractAddress: '0x' + 'bb'.repeat(20), fromName: 'Luis', inheritedAt: '2026-11-01T00:00:00Z' },
      { inheritedAccountId: 'i2', contractAddress: '0x' + 'cc'.repeat(20), fromName: 'Ana', inheritedAt: '2026-11-02T00:00:00Z' },
    ]));
    expect(smartNotificationSwitchTarget({ data_route: 'InheritedAccount', data_inheritedAccountId: 'i2' }, business))
      .toBe('smart_2');
  });

  it('falls back to personal_0 for an inherited account it does not know', () => {
    expect(smartNotificationSwitchTarget({ route: 'InheritedAccount', inheritedAccountId: 'i9' }, business))
      .toBe('personal_0');
    expect(smartNotificationSwitchTarget({ route: 'InheritedAccount' }, business)).toBe('personal_0');
  });
});

describe('alert triggered (Confío IA+)', () => {
  const { smartNotificationRoute: route } = require('../smartAccountNotificationRoute');
  it('opens the alerts list, from the in-app row or a push', () => {
    expect(route({ smart_account_event: 'watch_triggered', screen: 'SmartAccountWatches' }))
      .toEqual({ screen: 'SmartAccountWatches' });
    expect(route({ data_screen: 'SmartAccountWatches' })).toEqual({ screen: 'SmartAccountWatches' });
  });
});
