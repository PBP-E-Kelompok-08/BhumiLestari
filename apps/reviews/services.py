from django.db.models import Avg, Count, Max, Q

from .models import UlasanToko


def _ringkas(qs):
    """
    Kalkulasi agregasi rata-rata rating, total ulasan, dan distribusi bintang 1-5.
    Dioptimalkan menjadi 1 single database query menggunakan conditional aggregation
    (COUNT CASE WHEN), memangkas round-trip database hingga 50%.
    """
    data = qs.aggregate(
        rata=Avg("rating"),
        total=Count("id"),
        b5=Count("id", filter=Q(rating=5)),
        b4=Count("id", filter=Q(rating=4)),
        b3=Count("id", filter=Q(rating=3)),
        b2=Count("id", filter=Q(rating=2)),
        b1=Count("id", filter=Q(rating=1)),
    )
    return {
        "rata_rata": round(data["rata"] or 0, 1),
        "total": data["total"],
        "distribusi": {
            5: data["b5"],
            4: data["b4"],
            3: data["b3"],
            2: data["b2"],
            1: data["b1"],
        },
    }


def ringkasan_toko(toko_id):
    """Rating gabungan semua ulasan produk sebuah toko (id SellerProfile).
    Dipakai modul lain: `from apps.reviews.services import ringkasan_toko`."""
    return _ringkas(UlasanToko.objects.tampil().filter(toko_id=toko_id))


def ringkasan_produk(produk_id):
    """Rating satu produk (untuk header halaman produk)."""
    return _ringkas(UlasanToko.objects.tampil().filter(produk_id=produk_id))

# ---------------------------------------------------------------------------
# Data ulasan untuk halaman dashboard (Ringkasan Toko & Laporan Penjualan)
# ---------------------------------------------------------------------------
PERIODE_HARI = {"mingguan": 7, "bulanan": 30}
PERIODE_DEFAULT = "bulanan"
MAKS_BARIS_TABEL = 10


def baca_periode(nilai):
    """Normalisasi parameter ?periode= (mingguan = 7 hari terakhir, bulanan = 30 hari terakhir)."""
    return nilai if nilai in PERIODE_HARI else PERIODE_DEFAULT


def format_rata(rata):
    """4.2 -> '4,2' (format Indonesia)."""
    return f"{rata:.1f}".replace(".", ",")


def bintang(rata):
    """Daftar 5 boolean (True = bintang terisi) dari rata-rata, dibulatkan ke bintang terdekat."""
    penuh = int(rata + 0.5)
    return [i < penuh for i in range(5)]


def ringkasan_ulasan_toko(toko):
    """Untuk kartu 'Rating Toko' di halaman Ringkasan seller."""
    ringkasan = ringkasan_toko(toko.id)
    return {
        "ringkasan": ringkasan,
        "rata_teks": format_rata(ringkasan["rata_rata"]),
        "bintang": bintang(ringkasan["rata_rata"]),
    }


def laporan_ulasan(role, toko=None, periode=None):
    """Blok 'Ulasan dan Rating' di Laporan Penjualan.

    role 'seller' -> hanya toko miliknya (`toko` wajib), tabel per produk.
    role 'admin'  -> semua toko, tabel per toko.
    """
    from django.utils import timezone
    from datetime import timedelta

    from .models import LaporanUlasan

    periode = baca_periode(periode)
    sejak = timezone.now() - timedelta(days=PERIODE_HARI[periode])

    dasar = UlasanToko.objects.tampil()
    if role == "seller":
        dasar = dasar.filter(toko=toko)
    dalam_periode = dasar.filter(created_at__gte=sejak)

    agg = dalam_periode.aggregate(rata=Avg("rating"), total=Count("id"))
    rata_teks = format_rata(agg["rata"]) + " / 5" if agg["total"] else "-"

    if role == "seller":
        perlu = dasar.filter(balasan__isnull=True).count()
        kartu_ketiga = {"label": "Perlu Dibalas", "nilai": perlu}
        judul, kolom = "Rating per Produk", "Produk"
        baris_qs = dalam_periode.order_by().values("produk_id", "nama_produk").annotate(
            nama=Max("nama_produk"), jumlah=Count("id"), rata=Avg("rating")
        )
    else:
        menunggu = LaporanUlasan.objects.filter(status=LaporanUlasan.STATUS_MENUNGGU).count()
        kartu_ketiga = {"label": "Laporan Menunggu", "nilai": menunggu}
        judul, kolom = "Rating per Toko", "Toko"
        baris_qs = dalam_periode.order_by().values("toko_id", "toko__store_name").annotate(
            nama=Max("toko__store_name"), jumlah=Count("id"), rata=Avg("rating")
        )

    baris = [
        {"nama": r["nama"], "jumlah": r["jumlah"], "rata": format_rata(r["rata"])}
        for r in baris_qs.order_by("-rata", "-jumlah", "nama")[:MAKS_BARIS_TABEL]
    ]
    return {
        "periode": periode,
        "kartu": [
            {"label": "Rata-rata Rating", "nilai": rata_teks},
            {"label": "Ulasan Baru", "nilai": agg["total"]},
            kartu_ketiga,
        ],
        "judul_tabel": judul,
        "kolom_nama": kolom,
        "baris": baris,
    }


def rating_per_produk(produk_ids):
    """Rating beberapa produk sekaligus (1 query), untuk kartu produk di katalog.

    Return {produk_id: {"rata": 4.5, "rata_teks": "4,5", "jumlah": 12}}.
    Produk tanpa ulasan tidak ada di hasil."""
    baris = (
        UlasanToko.objects.tampil()
        .filter(produk_id__in=list(produk_ids))
        .order_by()
        .values("produk_id")
        .annotate(rata=Avg("rating"), jumlah=Count("id"))
    )
    return {
        r["produk_id"]: {
            "rata": round(r["rata"], 1),
            "rata_teks": format_rata(r["rata"]),
            "jumlah": r["jumlah"],
        }
        for r in baris
    }
