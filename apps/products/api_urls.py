from django.urls import path

from .api_views import (
    EcoFeatureListAPIView,
    ProductDetailAPIView,
    ProductListAPIView,
    ProductMineAPIView,
    ProductMineDetailAPIView,
    ProductVerificationDetailAPIView,
    ProductVerificationQueueAPIView,
)


app_name = "products_api"

urlpatterns = [
    path("", ProductListAPIView.as_view(), name="list"),
    path("mine/", ProductMineAPIView.as_view(), name="mine"),
    path("mine/<uuid:product_id>/", ProductMineDetailAPIView.as_view(), name="mine-detail"),
    path(
        "admin/verification/",
        ProductVerificationQueueAPIView.as_view(),
        name="verification-queue",
    ),
    path(
        "admin/verification/<uuid:product_id>/",
        ProductVerificationDetailAPIView.as_view(),
        name="verification-detail",
    ),
    path("eco-features/", EcoFeatureListAPIView.as_view(), name="eco-features"),
    path("<uuid:product_id>/", ProductDetailAPIView.as_view(), name="detail"),
]
