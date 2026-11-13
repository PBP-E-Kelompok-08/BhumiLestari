from rest_framework.permissions import BasePermission


class IsBuyer(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh pembeli."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and getattr(user, "role", None) == "buyer"
        )
