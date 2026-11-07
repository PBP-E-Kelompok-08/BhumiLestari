from django.urls import path

from .api_views import (
    BalasanUlasanAPIView,
    DaftarUlasanSayaAPIView,
    DaftarUlasanTokoAPIView,
    DetailUlasanAPIView,
)


app_name = "reviews_api"

urlpatterns = [
    path("toko/<int:toko_id>/", DaftarUlasanTokoAPIView.as_view(), name="daftar-toko"),
    path("saya/", DaftarUlasanSayaAPIView.as_view(), name="daftar-saya"),
    path("<int:pk>/", DetailUlasanAPIView.as_view(), name="detail"),
    path("<int:pk>/balasan/", BalasanUlasanAPIView.as_view(), name="balasan"),
]
