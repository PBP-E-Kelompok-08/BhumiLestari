from rest_framework.permissions import BasePermission


class IsBuyer(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh pembeli."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and getattr(user, "role", None) == "buyer"
        )


class IsSeller(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh seller."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and getattr(user, "role", None) == "seller"
        )


class IsBuyerOrSeller(BasePermission):
    message = "Endpoint ini hanya dapat digunakan oleh buyer atau seller."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated
            and getattr(user, "role", None) in {"buyer", "seller"}
        )


class IsSessionParticipantOrStaff(BasePermission):
    message = "Anda tidak memiliki akses ke sesi ini."

    def has_object_permission(self, request, view, obj):
        user = request.user
        return bool(
            user.is_authenticated
            and (user in (obj.buyer, obj.seller) or user.is_staff)
        )
