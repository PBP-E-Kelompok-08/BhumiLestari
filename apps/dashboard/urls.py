from django.urls import path

from apps.dashboard.views import *

app_name = "dashboard"

urlpatterns = [
    path("", show_dashboard_home, name="show_dashboard_home"),
]