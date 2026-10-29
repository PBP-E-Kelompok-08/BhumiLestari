from django.urls import path

from apps.checkout import views

app_name = "checkout"

urlpatterns = [
    path("cart/", views.show_cart, name="show_cart"),
    path("cart/add/<uuid:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_item, name="update_cart_item"),
    path("cart/select/", views.select_cart_items, name="select_cart_items"),
    path("cart/delete/", views.delete_cart_items, name="delete_cart_items"),
    path("checkout/", views.show_checkout, name="show_checkout"),
    path("pesanan/", views.order_list, name="order_list"),
    path("pesanan/<int:order_id>/", views.order_detail, name="order_detail"),
]