from django.urls import path, include
from . import views

from django.conf import settings
from django.conf.urls.static import static

app_name = "products"

urlpatterns = [
    path("tambah/", views.add_product, name="add_product"),
    path("<uuid:pk>/edit/", views.edit_product, name="edit_product"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)