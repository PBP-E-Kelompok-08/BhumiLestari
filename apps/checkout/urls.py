from django.urls import path

from apps.checkout.views import *

app_name = "checkout"

urlpatterns = [path("cart/", show_cart, name="show_cart"),
               path("checkout/", show_checkout, name="show_checkout"),
]