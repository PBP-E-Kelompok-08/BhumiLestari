from django.urls import path

from .api_views import SellerSummaryAPIView


app_name = "dashboard_api"

urlpatterns = [
    path("seller/summary/", SellerSummaryAPIView.as_view(), name="seller-summary"),
]
