from django.db.models import Avg, Count

from .models import UlasanToko


def _ringkas(qs):
    agg = qs.aggregate(rata=Avg("rating"), total=Count("id"))
    distribusi = {r: 0 for r in (5, 4, 3, 2, 1)}
    for row in qs.order_by().values("rating").annotate(n=Count("id")):
        distribusi[row["rating"]] = row["n"]
    return {
        "rata_rata": round(agg["rata"] or 0, 1),
        "total": agg["total"],
        "distribusi": distribusi,
    }


def ringkasan_toko(toko_id):
    """Rating gabungan semua ulasan produk sebuah toko (id SellerProfile).
    Dipakai modul lain: `from apps.reviews.services import ringkasan_toko`."""
    return _ringkas(UlasanToko.objects.tampil().filter(toko_id=toko_id))


def ringkasan_produk(produk_id):
    """Rating satu produk (untuk header halaman produk)."""
    return _ringkas(UlasanToko.objects.tampil().filter(produk_id=produk_id))