from django.urls import path

from apps.dashboard.views import *

app_name = "dashboard"

urlpatterns = [
    path("", show_dashboard_home, name="show_dashboard_home"),
    path("api/products/", api_products, name="api_products"),
    path("ringkasan/", seller_summary, name="seller_summary"),
    path("laporan/", sales_report, name="sales_report"),
]