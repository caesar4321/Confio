"""
GraphQL middleware to automatically track user activity on mutations

This middleware automatically calls touch_last_activity() for all authenticated mutations,
ensuring comprehensive activity tracking without manual calls in every mutation.
"""

from graphql import GraphQLResolveInfo
from users.activity_tracking import touch_last_activity
import logging

logger = logging.getLogger(__name__)


class ActivityTrackingMiddleware:
    """
    Middleware that tracks user activity on GraphQL mutations.

    This automatically updates last_activity_at for all authenticated mutations,
    providing comprehensive DAU/MAU tracking without requiring manual calls
    in every mutation resolver.

    Important: Only mutations are tracked, not queries.
    This ensures we track meaningful user actions, not just data fetching.
    """

    def resolve(self, next, root, info: GraphQLResolveInfo, **args):
        # Get the result first
        result = next(root, info, **args)

        # Only track on mutations (not queries)
        if info.operation.operation != 'mutation':
            return result

        # Only track if user is authenticated
        context = info.context
        user = getattr(context, 'user', None)

        if user and user.is_authenticated:
            # Track activity asynchronously to avoid blocking the mutation
            try:
                touch_last_activity(user)
            except Exception as e:
                # Log error but don't fail the mutation
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
