from django.urls import path
from . import views

from django.conf import settings
from django.conf.urls.static import static

app_name = "products"

urlpatterns = [
    path("tambah/", views.add_product, name="add_product"),
    path("<uuid:pk>/edit/", views.edit_product, name="edit_product"),
    path("<uuid:pk>/hapus/", views.delete_product, name="delete_product"),
    path("verifikasi/", views.verification_queue, name="verification_queue"),
    path("<uuid:pk>/tinjau/", views.review_product_admin, name="review_product_admin"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)