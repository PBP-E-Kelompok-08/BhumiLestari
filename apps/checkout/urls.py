from django.urls import path

from apps.checkout import views

app_name = "checkout"

urlpatterns = [
    path("cart/", views.show_cart, name="show_cart"),
    path("cart/add/<uuid:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("checkout/", views.show_checkout, name="show_checkout"),
]