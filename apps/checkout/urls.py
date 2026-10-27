from django.urls import path

from apps.checkout.views import *

app_name = "checkout"

urlpatterns = [
    path("pesanan/", order_list, name="order_list"),
    path("pesanan/tes/", order_detail, name="order_detail"),
]