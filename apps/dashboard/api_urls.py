from django.urls import path

from .api_views import SalesReportAPIView, SellerSummaryAPIView


app_name = "dashboard_api"

urlpatterns = [
    path("seller/summary/", SellerSummaryAPIView.as_view(), name="seller-summary"),
    path("sales-report/", SalesReportAPIView.as_view(), name="sales-report"),
]
