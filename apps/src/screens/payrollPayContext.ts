/**
 * Which account a payroll item has to be paid FROM.
 *
 * A delegate lives in their PERSONAL account, and that is not an accident:
 * `pendingPayrollItems` serves them there deliberately (payroll/schema.py —
 * "fall back to delegate view (employee of any business)"), and the Home
 * payroll card routes them here from it. But the payout mutation needs a
 * validated BUSINESS JWT, because that is the only branch of
 * get_jwt_business_context_with_validation where the send_funds permission
 * check actually runs. Paying from personal context therefore died on
 * `business_context_required` — a raw code the client had no Spanish for.
 *
 * So the screen switches context before it moves money, and these two
 * decide where to. Kept in their own module so the rule can be tested
 * without mounting a screen that pulls in half of React Native.
 */

/** Shape-tolerant on purpose: callers pass GraphQL rows and context accounts. */
type PayrollItemLike = { run?: { business?: { id?: string | number; name?: string } } };
type AccountLike = { id?: string; type?: string; business?: { id?: string | number } };

const businessIdOf = (item?: PayrollItemLike | null): string =>
  String(item?.run?.business?.id ?? '');

/**
 * The business account this item pays from, or null when the user holds no
 * such account.
 *
 * Matched on the BUSINESS id, never on "is some business account": an
 * employee can be a delegate at more than one business, and paying company
 * A's payroll out of company B's context would spend a different company's
 * money.
 */
export const payrollPayAccountFor = (
  item?: PayrollItemLike | null,
  accounts?: AccountLike[] | null,
): AccountLike | null => {
  const businessId = businessIdOf(item);
  if (!businessId) return null;
  return (accounts || []).find(
    (a) => a?.type === 'business' && String(a?.business?.id ?? '') === businessId,
  ) || null;
};

/** True when the active account is ALREADY the one this item pays from. */
export const isPayrollContextReady = (
  item?: PayrollItemLike | null,
  activeAccount?: AccountLike | null,
): boolean => {
  const businessId = businessIdOf(item);
  return !!businessId
    && activeAccount?.type === 'business'
    && String(activeAccount?.business?.id ?? '') === businessId;
};
