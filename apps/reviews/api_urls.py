from django.urls import path

from .api_views import DaftarUlasanTokoAPIView


app_name = "reviews_api"

urlpatterns = [
    path("toko/<int:toko_id>/", DaftarUlasanTokoAPIView.as_view(), name="daftar-toko"),
]
