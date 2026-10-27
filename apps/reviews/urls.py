from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    # halaman HTML
    path("halaman/toko/<int:toko_id>/", views.halaman_toko, name="halaman_toko"),
    path("halaman/saya/", views.halaman_saya, name="halaman_saya"),
    path("halaman/penjual/", views.halaman_penjual, name="halaman_penjual"),
    # baca (JSON)
    path("toko/<int:toko_id>/", views.daftar_ulasan, name="daftar"),
    path("saya/", views.ulasan_saya, name="saya"),
    path("penjual/", views.ulasan_penjual, name="penjual"),
    # buyer
    path("toko/<int:toko_id>/tambah/", views.tambah_ulasan, name="tambah"),
    path("<int:pk>/edit/", views.edit_ulasan, name="edit"),
    path("<int:pk>/hapus/", views.hapus_ulasan, name="hapus"),
    # seller
    path("<int:pk>/balas/", views.balas_ulasan, name="balas"),
    path("<int:pk>/balas/edit/", views.edit_balasan, name="balas_edit"),
    path("<int:pk>/balas/hapus/", views.hapus_balasan, name="balas_hapus"),
    path("<int:pk>/laporkan/", views.laporkan_ulasan, name="laporkan"),
]
