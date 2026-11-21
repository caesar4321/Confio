// Where a Cuenta inteligente notification opens (smart_account/notifications.py).
//
// The server puts the target screen in the notification's data. The in-app
// list sees that data as is; a push carries it flattened with a `data_`
// prefix (notifications/fcm_service.py). The key is `route` (the agreed
// name) or `screen` (what the server writes today); both are read. Only the
// screens below are accepted, so a stray value never navigates anywhere.
//
// The ids are opaque server ids the screens re-check with the server; they
// carry no authority.
import { knownInheritedSmartAccountId } from './smartAccounts';

export type SmartNotificationTarget =
  | { screen: 'SmartAccountHome' | 'SmartAccountBilling' | 'SmartAccountRules' | 'SmartAccountWatches' | 'BeneficiaryStatus'; params?: undefined }
  | { screen: 'BeneficiaryInvite' | 'BeneficiaryClaimStatus'; params: { designationId: string } }
  | { screen: 'InheritedAccount'; params?: { inheritedAccountId: string } }
  | { screen: 'BottomTabs'; params: { screen: 'Home' } };

// SmartAccountWatches: an alert the owner set through Confío IA+ was met.
const PLAIN = new Set(['SmartAccountHome', 'SmartAccountBilling', 'SmartAccountRules', 'SmartAccountWatches', 'BeneficiaryStatus']);
const WITH_DESIGNATION = new Set(['BeneficiaryInvite', 'BeneficiaryClaimStatus']);

const pick = (data: Record<string, unknown>, key: string): string | null => {
  for (const k of [key, `data_${key}`, `extra_${key}`]) {
    const v = data[k];
    if (typeof v === 'string' && v.trim().length > 0 && v.length <= 128) {
      return v.trim();
    }
  }
  return null;
};

export function smartNotificationRoute(raw: unknown): SmartNotificationTarget | null {
  let data: unknown = raw;
  if (typeof data === 'string') {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }
  if (!data || typeof data !== 'object') {
    return null;
  }
  const d = data as Record<string, unknown>;
  const route = [pick(d, 'route'), pick(d, 'screen')].find(
    (r) => !!r && (PLAIN.has(r) || WITH_DESIGNATION.has(r) || r === 'InheritedAccount'),
  );
  if (!route) {
    return null;
  }
  if (PLAIN.has(route)) {
    return { screen: route as 'SmartAccountHome' };
  }
  if (WITH_DESIGNATION.has(route)) {
    const designationId = pick(d, 'designationId') ?? pick(d, 'designation_id');
    // Without the id these screens cannot know which account. Inicio's
    // Cuenta inteligente row resolves the person's designation whether or
    // not they have an account of their own (SmartAccountHome would show a
    // non-subscriber "esta cuenta ya no está abierta").
    return designationId
      ? { screen: route as 'BeneficiaryInvite', params: { designationId } }
      : { screen: 'BottomTabs', params: { screen: 'Home' } };
  }
  const inheritedAccountId = pick(d, 'inheritedAccountId') ?? pick(d, 'inherited_account_id');
  return inheritedAccountId
    ? { screen: 'InheritedAccount', params: { inheritedAccountId } }
    : { screen: 'InheritedAccount' };
}

/**
 * The account a Cuenta inteligente notification must open in, when the
 * active context cannot show it. A Cuenta inteligente belongs to the person,
 * never to a business: from a business context (owner or employee) the tap
 * first switches to the personal wallet (personal_0), or, for an inherited
 * account this session already knows, straight to its smart_N. From a
 * personal or smart context nothing switches. null = no switch (or not a
 * smart notification).
 */
export function smartNotificationSwitchTarget(
  raw: unknown,
  current: { type?: string | null } | null | undefined,
): string | null {
  const target = smartNotificationRoute(raw);
  if (!target || current?.type !== 'business') {
    return null;
  }
  if (target.screen === 'InheritedAccount') {
    return knownInheritedSmartAccountId(target.params?.inheritedAccountId) ?? 'personal_0';
  }
  return 'personal_0';
}
