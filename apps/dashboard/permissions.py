from rest_framework.permissions import BasePermission


class IsSeller(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh seller."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and getattr(user, "role", None) == "seller"
        )


class IsSellerOrAdmin(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh seller atau admin."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and (
                user.is_superuser
                or getattr(user, "role", None) == "seller"
            )
        )
