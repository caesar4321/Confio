# One unpaid Koywe deposit per user

New Koywe on-ramp orders are refused while the user has any local `PENDING`
Koywe on-ramp transaction. This includes waiting-for-payment orders and
unresolved creation attempts. The restriction spans accounts, wallet addresses,
countries, payment methods and both `cusd` / `cusd_plus` destinations.

The early check avoids unnecessary provider and Face work. The authoritative
check locks the user row and inserts a pre-provider reservation in the same
database transaction, before releasing the lock and calling Koywe. Concurrent
devices cannot both pass the check. Definitively rejected creation releases the
reservation; ambiguous outcomes retain it for reconciliation.

No order is expired using local age, and no existing payment request is cancelled
by this change. Provider-confirmed terminal states release the slot. Paid orders
mapped to `PROCESSING` no longer occupy the *unpaid* slot. Off-ramps and other
providers are outside this rule. Multiple historical unpaid orders are retained;
all must stop being pending before another deposit order can be created.

Webhooks and the existing Koywe polling task reconcile provider status. Unpaid
deposits with a provider ID remain eligible for polling beyond the previous
seven-day window. Unknown creations without a provider ID still require webhook
recovery or support reconciliation. Users receive a Spanish message asking them
to finish the existing recharge or wait for confirmed cancellation/expiry.

For a known provider order, a blocked creation returns `nextStep=resume_order`
and the original order ID, country, currency, destination and payment method.
The app offers "Ver recarga pendiente" and fetches fresh provider instructions.
It never reuses the attempted replacement's quote or a cached QR. Unknown
creations without an order ID do not offer this resume action. Older apps still
receive the refusal message. Deploy the backend before the app which requests
the new `destination` response field.

This guard is independent of the Face rollout switch and needs no migration.
It does not implement provider-side forced expiry or invalidate an existing QR.
