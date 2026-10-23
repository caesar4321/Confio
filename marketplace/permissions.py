"""Who may act for an account in Comprar.

Stores and purchases ride the JWT's account, personal OR business, like the
rest of the app. A personal account is its user's alone; a business account
is its owner's, and an active employee's for the permissions their role holds
(negative-check: only explicitly allowed actions, explicit revocations win).
Rechecked at the moment money moves, never trusted from an earlier gate.
"""

# Comprar action → the business permission it needs.
STORE_ADMIN = 'edit_business_info'   # open/edit the store, listings, photos
VIEW_ORDERS = 'view_transactions'    # see orders (and delivery details)
BUY = 'send_funds'                   # pay, confirm, dispute, reclaim, rate
SHIP = 'accept_payments'             # mark shipped, tracking
REFUND = 'send_funds'                # money back out of the store's escrow

ACTION_PERMISSIONS = {
    'deposit': BUY, 'confirm': BUY, 'dispute': BUY, 'reclaim': BUY,
    'ship': SHIP, 'refund': REFUND,
}


class AccountError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def account_for(user, jwt_ctx):
    """The JWT's account (personal or business). The business gate itself
    (ownership / employee permission) ran in get_jwt_business_context_with_validation."""
    from users.models import Account

    if not jwt_ctx or not user:
        raise AccountError('account_not_found')
    if jwt_ctx.get('account_type') == 'business' and jwt_ctx.get('business_id'):
        account = Account.objects.filter(
            business_id=jwt_ctx['business_id'], account_type='business', deleted_at__isnull=True,
            account_index=jwt_ctx.get('account_index', 0)).select_related('business').first()
    else:
        account = user.accounts.filter(
            account_type='personal', deleted_at__isnull=True,
            account_index=jwt_ctx.get('account_index', 0)).first()
    if account is None:
        raise AccountError('account_not_found')
    return account


def can_act_for(user, account, permission: str) -> bool:
    """Is `user` allowed to do `permission` for `account` RIGHT NOW?"""
    if account is None or account.deleted_at is not None:
        return False
    if account.account_type == 'personal':
        return account.user_id == user.id
    from users.jwt_context import business_permission_is_current
    return business_permission_is_current(user, account.business_id, permission)


def order_actor_account(order, action: str):
    """The side of the order that performs `action`."""
    from .escrow import ACTIONS
    return order.buyer_account if ACTIONS[action][1] == 'buyer' else order.store.owner_account
