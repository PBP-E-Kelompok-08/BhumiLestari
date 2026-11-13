from django.urls import path

from .api_views import (
    CartAPIView,
    CartItemCreateAPIView,
    CartItemDetailAPIView,
    CartSelectionAPIView,
    CheckoutCreateAPIView,
    CheckoutSummaryAPIView,
)


app_name = "checkout_api"

urlpatterns = [
    path("cart/", CartAPIView.as_view(), name="cart"),
    path("cart/items/", CartItemCreateAPIView.as_view(), name="item-create"),
    path(
        "cart/items/<int:item_id>/",
        CartItemDetailAPIView.as_view(),
        name="item-detail",
    ),
    path(
        "cart/selection/",
        CartSelectionAPIView.as_view(),
        name="selection",
    ),
    path("summary/", CheckoutSummaryAPIView.as_view(), name="summary"),
    path("orders/", CheckoutCreateAPIView.as_view(), name="order-create"),
]
