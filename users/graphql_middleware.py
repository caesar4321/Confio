"""
GraphQL middleware to automatically track user activity

This middleware calls touch_last_activity() for every authenticated query and
mutation, so opening the app counts as activity (the usual DAU/MAU definition),
not only actions that change something.
"""

from graphql import GraphQLResolveInfo, OperationType
from users.activity_tracking import touch_last_activity
import logging

logger = logging.getLogger(__name__)

TRACKED_OPERATIONS = (OperationType.QUERY, OperationType.MUTATION)


class ActivityTrackingMiddleware:
    """
    Middleware that tracks user activity on authenticated GraphQL requests.

    Queries count too: a member who opens the app and only reads a balance is
    an active user. Subscriptions do not, since a held-open socket is not a
    visit. touch_last_activity() keeps a per-user cooldown, so this costs at
    most one write per user every few minutes.
    """

    def resolve(self, next, root, info: GraphQLResolveInfo, **args):
        # Get the result first
        result = next(root, info, **args)

        # graphql-core 3 gives an OperationType enum here, not a string.
        if info.operation.operation not in TRACKED_OPERATIONS:
            return result

        # Middleware runs for every field; touch once per root field,
        # not once per nested field of its payload.
        if info.path.prev is not None:
            return result

        # Only track if user is authenticated
        context = info.context
        user = getattr(context, 'user', None)

        # A request with several root fields touches once.
        if getattr(context, '_activity_tracked', False) is True:
            return result

        if user and user.is_authenticated:
            try:
                context._activity_tracked = True
                touch_last_activity(user)
            except Exception as e:
                # Log error but don't fail the request
                logger.error(f"Failed to track activity for user {user.id}: {e}")

        return result


# Alternative: Decorator for explicit activity tracking
def track_activity(mutation_class):
    """
    Decorator to explicitly mark mutations that should track activity.

    Use this if you want more granular control over which mutations
    update last_activity_at.

    Usage:
        @track_activity
        class SendMoney(graphene.Mutation):
            ...
    """
    original_mutate = mutation_class.mutate

    @classmethod
    def mutate_with_tracking(cls, root, info, **kwargs):
        # Call original mutation
        result = original_mutate(root, info, **kwargs)

        # Track activity if user is authenticated
        user = getattr(info.context, 'user', None)
        if user and user.is_authenticated:
            try:
                touch_last_activity(user)
            except Exception as e:
                logger.error(f"Failed to track activity: {e}")

        return result

    mutation_class.mutate = mutate_with_tracking
    return mutation_class


class ReaderCountryMiddleware:
    """Text the server writes for this request (Comunidad snippets, post
    bodies) uses the signed-in reader's number format (users/number_format).
    Set on every top-level field so a reused worker never keeps the previous
    request's reader."""

    def resolve(self, next, root, info: GraphQLResolveInfo, **args):
        if root is None:
            from users.number_format import set_reader

            user = getattr(info.context, 'user', None)
            set_reader(user if user is not None and getattr(user, 'is_authenticated', False) else None)
        return next(root, info, **args)
