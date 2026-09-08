from rest_framework.permissions import BasePermission


class HasBillingScope(BasePermission):
    def has_permission(self, request, view):
        required = getattr(view, 'required_scope', '')
        return bool(request.user and request.user.is_authenticated
                    and required in request.user.scopes)

