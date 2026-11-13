from django.urls import path

from .api_views import (
    EcoFeatureListAPIView,
    ProductDetailAPIView,
    ProductListAPIView,
)


app_name = "products_api"

urlpatterns = [
    path("", ProductListAPIView.as_view(), name="list"),
    path("eco-features/", EcoFeatureListAPIView.as_view(), name="eco-features"),
    path("<uuid:product_id>/", ProductDetailAPIView.as_view(), name="detail"),
]
