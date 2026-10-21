from django.contrib import admin

from .models import BalasanUlasan, FotoUlasan, LaporanUlasan, UlasanToko


class FotoInline(admin.TabularInline):
    model = FotoUlasan
    extra = 0


class BalasanInline(admin.StackedInline):
    model = BalasanUlasan
    extra = 0


@admin.register(UlasanToko)
class UlasanTokoAdmin(admin.ModelAdmin):
    list_display = ("toko", "pembeli", "nama_produk", "rating", "disembunyikan", "created_at")
    list_filter = ("rating", "disembunyikan")
    inlines = [FotoInline, BalasanInline]


@admin.register(LaporanUlasan)
class LaporanUlasanAdmin(admin.ModelAdmin):
    list_display = ("ulasan", "pelapor", "alasan", "status", "created_at")
    list_filter = ("status",)
    actions = ["terima_laporan", "tolak_laporan"]

    @admin.action(description="Terima laporan (sembunyikan ulasan)")
    def terima_laporan(self, request, queryset):
        UlasanToko.objects.filter(laporan__in=queryset).update(disembunyikan=True)
        queryset.update(status=LaporanUlasan.STATUS_DITERIMA)

    @admin.action(description="Tolak laporan (ulasan tetap tampil)")
    def tolak_laporan(self, request, queryset):
        queryset.update(status=LaporanUlasan.STATUS_DITOLAK)