from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

BATAS_EDIT_ULASAN = timedelta(days=7)   # pembeli: edit ulasan
BATAS_EDIT_BALASAN = timedelta(days=1)  # penjual: edit balasan (dihitung dari waktu balasan)


class UlasanQuerySet(models.QuerySet):
    def tampil(self):
        """Ulasan yang boleh tampil publik & dihitung ke rating (bukan yang disembunyikan admin)."""
        return self.filter(disembunyikan=False)


class UlasanToko(models.Model):
    """Ulasan satu produk yang sudah dibeli; dikumpulkan di level toko."""

    toko = models.ForeignKey(
        "users.SellerProfile", on_delete=models.CASCADE, related_name="ulasan_toko"
    )
    pembeli = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ulasan_dibuat"
    )
    # TODO: setelah model Produk ada, ganti jadi
    #   produk = models.ForeignKey("products.Product", null=True, on_delete=models.SET_NULL)
    produk_id = models.PositiveIntegerField()
    nama_produk = models.CharField(max_length=150)  # salinan nama, tetap tampil jika produk dihapus
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    komentar = models.TextField(max_length=1000, blank=True)
    diedit = models.BooleanField(default=False)
    disembunyikan = models.BooleanField(default=False)  # diset admin saat laporan diterima
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UlasanQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["pembeli", "produk_id"], name="satu_ulasan_per_produk_per_pembeli"
            )
        ]
        indexes = [
            models.Index(fields=["toko", "-created_at"]),
            models.Index(fields=["toko", "produk_id"]),
        ]
        verbose_name = "Ulasan Toko"
        verbose_name_plural = "Ulasan Toko"

    def __str__(self):
        return f"{self.pembeli} -> {self.toko} / {self.nama_produk} ({self.rating}/5)"

    def bisa_diedit(self):
        return timezone.now() - self.created_at < BATAS_EDIT_ULASAN


class FotoUlasan(models.Model):
    ulasan = models.ForeignKey(UlasanToko, on_delete=models.CASCADE, related_name="foto")
    gambar = models.ImageField(upload_to="ulasan/%Y/%m/")

    class Meta:
        verbose_name = "Foto Ulasan"
        verbose_name_plural = "Foto Ulasan"


class BalasanUlasan(models.Model):
    ulasan = models.OneToOneField(UlasanToko, on_delete=models.CASCADE, related_name="balasan")
    penjual = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="balasan_ulasan"
    )
    pesan = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Balasan Ulasan"
        verbose_name_plural = "Balasan Ulasan"

    def bisa_diedit(self):
        return timezone.now() - self.created_at < BATAS_EDIT_BALASAN


class LaporanUlasan(models.Model):
    STATUS_MENUNGGU = "menunggu"
    STATUS_DITERIMA = "diterima"
    STATUS_DITOLAK = "ditolak"
    CHOICE_STATUS = [
        (STATUS_MENUNGGU, "Menunggu"),
        (STATUS_DITERIMA, "Diterima"),
        (STATUS_DITOLAK, "Ditolak"),
    ]

    ulasan = models.ForeignKey(UlasanToko, on_delete=models.CASCADE, related_name="laporan")
    pelapor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="laporan_ulasan"
    )
    alasan = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=CHOICE_STATUS, default=STATUS_MENUNGGU)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Laporan Ulasan"
        verbose_name_plural = "Laporan Ulasan"
        constraints = [
            models.UniqueConstraint(fields=["ulasan", "pelapor"], name="satu_laporan_per_ulasan")
        ]

    def __str__(self):
        return f"Laporan #{self.pk} ({self.status})"