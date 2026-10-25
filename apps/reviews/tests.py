import shutil
import tempfile
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.products.models import Product
from apps.users.models import SellerProfile

from . import integrations
from .models import BalasanUlasan, LaporanUlasan, UlasanToko
from .services import (
    baca_periode,
    bintang,
    format_rata,
    laporan_ulasan,
    ringkasan_produk,
    ringkasan_toko,
    ringkasan_ulasan_toko,
)

User = get_user_model()
MEDIA = tempfile.mkdtemp()


def buat_buyer(nama="budi"):
    return User.objects.create_user(
        username=nama, email=f"{nama}@test.com", password="pw12345!", role="buyer", full_name=nama
    )


def buat_seller(nama="sari", toko="Toko Sari"):
    user = User.objects.create_user(
        username=nama, email=f"{nama}@test.com", password="pw12345!", role="seller"
    )
    return user, SellerProfile.objects.create(user=user, store_name=toko)


def buat_admin():
    return User.objects.create_superuser(
        username="admin", email="admin@test.com", password="pw12345!"
    )


def buat_produk(profile, nama="Sedotan Bambu"):
    return Product.objects.create(
        seller=profile,
        name=nama,
        description="deskripsi",
        category="daily_supplies",
        materials="bambu",
        origin="Bandung",
        price=10000,
        stock=5,
        image=SimpleUploadedFile("a.png", b"x", content_type="image/png"),
        verification_document=SimpleUploadedFile("d.pdf", b"x", content_type="application/pdf"),
    )


def buat_ulasan(toko, pembeli, produk, rating, **kw):
    return UlasanToko.objects.create(
        toko=toko, pembeli=pembeli, produk=produk, nama_produk=produk.name, rating=rating, **kw
    )


def tua(ulasan, hari):
    """Geser created_at ke belakang (auto_now_add tidak bisa diisi saat create)."""
    UlasanToko.objects.filter(pk=ulasan.pk).update(created_at=timezone.now() - timedelta(days=hari))


@override_settings(MEDIA_ROOT=MEDIA)
class DasarTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.seller_user, self.toko = buat_seller()
        self.produk = buat_produk(self.toko)
        self.b1, self.b2 = buat_buyer("b1"), buat_buyer("b2")


class ServiceRingkasanTest(DasarTest):
    def test_ringkasan_toko_mengabaikan_ulasan_disembunyikan(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, self.produk, 1, disembunyikan=True)
        hasil = ringkasan_toko(self.toko.id)
        self.assertEqual(hasil["total"], 1)
        self.assertEqual(hasil["rata_rata"], 5.0)
        self.assertEqual(hasil["distribusi"][5], 1)

    def test_ringkasan_produk_memakai_uuid(self):
        buat_ulasan(self.toko, self.b1, self.produk, 4)
        buat_ulasan(self.toko, self.b2, self.produk, 2)
        self.assertEqual(ringkasan_produk(self.produk.pk)["rata_rata"], 3.0)
        self.assertEqual(ringkasan_produk(uuid.uuid4())["total"], 0)

    def test_ulasan_tetap_ada_saat_produk_dihapus(self):
        u = buat_ulasan(self.toko, self.b1, self.produk, 5)
        self.produk.delete()
        u.refresh_from_db()
        self.assertIsNone(u.produk)
        self.assertEqual(u.nama_produk, "Sedotan Bambu")

    def test_satu_ulasan_per_produk_per_pembeli(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            buat_ulasan(self.toko, self.b1, self.produk, 3)

    def test_helper_format(self):
        self.assertEqual(format_rata(4.2), "4,2")
        self.assertEqual(bintang(4.2), [True, True, True, True, False])
        self.assertEqual(bintang(4.5), [True] * 5)
        self.assertEqual(bintang(0), [False] * 5)
        self.assertEqual(baca_periode("mingguan"), "mingguan")
        self.assertEqual(baca_periode("ngawur"), "bulanan")
        self.assertEqual(baca_periode(None), "bulanan")

    def test_ringkasan_ulasan_toko_kosong(self):
        hasil = ringkasan_ulasan_toko(self.toko)
        self.assertEqual(hasil["ringkasan"]["total"], 0)
        self.assertEqual(hasil["bintang"], [False] * 5)


class ServiceLaporanTest(DasarTest):
    def setUp(self):
        super().setUp()
        self.user2, self.toko2 = buat_seller("rini", "Toko Rini")
        self.produk2 = buat_produk(self.toko2, "Tas Kain")

    def test_seller_hanya_melihat_tokonya(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko2, self.b1, self.produk2, 1)
        hasil = laporan_ulasan("seller", toko=self.toko, periode="bulanan")
        self.assertEqual(hasil["judul_tabel"], "Rating per Produk")
        self.assertEqual([b["nama"] for b in hasil["baris"]], ["Sedotan Bambu"])
        self.assertEqual(hasil["kartu"][0]["nilai"], "5,0 / 5")
        self.assertEqual(hasil["kartu"][1]["nilai"], 1)

    def test_periode_mingguan_vs_bulanan(self):
        lama = buat_ulasan(self.toko, self.b1, self.produk, 5)
        tua(lama, 10)
        buat_ulasan(self.toko, self.b2, self.produk, 3)
        self.assertEqual(laporan_ulasan("seller", self.toko, "mingguan")["kartu"][1]["nilai"], 1)
        self.assertEqual(laporan_ulasan("seller", self.toko, "bulanan")["kartu"][1]["nilai"], 2)
        tua(lama, 45)
        self.assertEqual(laporan_ulasan("seller", self.toko, "bulanan")["kartu"][1]["nilai"], 1)

    def test_perlu_dibalas_hanya_menghitung_yang_belum_dibalas(self):
        u1 = buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, self.produk, 4)
        BalasanUlasan.objects.create(ulasan=u1, penjual=self.seller_user, pesan="Terima kasih")
        kartu = laporan_ulasan("seller", self.toko)["kartu"][2]
        self.assertEqual(kartu, {"label": "Perlu Dibalas", "nilai": 1})

    def test_admin_melihat_semua_toko_dan_laporan_menunggu(self):
        u1 = buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko2, self.b1, self.produk2, 3)
        LaporanUlasan.objects.create(ulasan=u1, pelapor=self.seller_user, alasan="spam")
        LaporanUlasan.objects.create(
            ulasan=u1, pelapor=self.user2, alasan="kasar", status=LaporanUlasan.STATUS_DITOLAK
        )
        hasil = laporan_ulasan("admin")
        self.assertEqual(hasil["judul_tabel"], "Rating per Toko")
        self.assertEqual([b["nama"] for b in hasil["baris"]], ["Toko Sari", "Toko Rini"])
        self.assertEqual(hasil["kartu"][2], {"label": "Laporan Menunggu", "nilai": 1})

    def test_tanpa_ulasan(self):
        hasil = laporan_ulasan("seller", self.toko)
        self.assertEqual(hasil["kartu"][0]["nilai"], "-")
        self.assertEqual(hasil["baris"], [])


class ViewDashboardTest(DasarTest):
    def test_guest_diarahkan_ke_login(self):
        for nama in ("dashboard:seller_summary", "dashboard:sales_report"):
            r = self.client.get(reverse(nama))
            self.assertRedirects(r, reverse("users:login"), fetch_redirect_response=False)

    def test_buyer_tidak_boleh(self):
        self.client.force_login(self.b1)
        for nama in ("dashboard:seller_summary", "dashboard:sales_report"):
            r = self.client.get(reverse(nama))
            self.assertRedirects(
                r, reverse("dashboard:show_dashboard_home"), fetch_redirect_response=False
            )

    def test_seller_tanpa_profil_diarahkan_ke_beranda(self):
        tanpa = User.objects.create_user(
            username="x", email="x@test.com", password="pw12345!", role="seller"
        )
        self.client.force_login(tanpa)
        for nama in ("dashboard:seller_summary", "dashboard:sales_report"):
            r = self.client.get(reverse(nama))
            self.assertRedirects(
                r, reverse("dashboard:show_dashboard_home"), fetch_redirect_response=False
            )

    def test_ringkasan_seller_belum_ada_ulasan(self):
        self.client.force_login(self.seller_user)
        r = self.client.get(reverse("dashboard:seller_summary"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ringkasan Toko Toko Sari")
        self.assertContains(r, "Belum ada ulasan.")

    def test_ringkasan_seller_menampilkan_rating_dinamis(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, self.produk, 3)
        self.client.force_login(self.seller_user)
        r = self.client.get(reverse("dashboard:seller_summary"))
        self.assertContains(r, "4,0/5")
        self.assertContains(r, "2 ulasan")
        self.assertNotContains(r, "1510 ulasan")

    def test_laporan_seller(self):
        buat_ulasan(self.toko, self.b1, self.produk, 4)
        self.client.force_login(self.seller_user)
        r = self.client.get(reverse("dashboard:sales_report"), {"periode": "mingguan"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rating per Produk")
        self.assertContains(r, "Sedotan Bambu")
        self.assertContains(r, "Perlu Dibalas")

    def test_laporan_admin(self):
        buat_ulasan(self.toko, self.b1, self.produk, 4)
        self.client.force_login(buat_admin())
        r = self.client.get(reverse("dashboard:sales_report"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Rating per Toko")
        self.assertContains(r, "Toko Sari")
        self.assertContains(r, "Laporan Menunggu")

    def test_laporan_periode_tidak_valid_memakai_default(self):
        self.client.force_login(self.seller_user)
        r = self.client.get(reverse("dashboard:sales_report"), {"periode": "tahunan"})
        self.assertEqual(r.status_code, 200)


class TambahUlasanUUIDTest(DasarTest):
    def setUp(self):
        super().setUp()
        self.url = reverse("reviews:tambah", args=[self.toko.id])
        self.client.force_login(self.b1)

    def kirim(self, **data):
        isi = {"rating": "5", "komentar": "Bagus", "produk_id": str(self.produk.pk)}
        isi.update(data)
        return self.client.post(self.url, isi)

    def test_berhasil_dengan_produk_uuid(self):
        r = self.kirim()
        self.assertEqual(r.status_code, 201)
        u = UlasanToko.objects.get()
        self.assertEqual(u.produk_id, self.produk.pk)
        self.assertEqual(u.nama_produk, "Sedotan Bambu")
        self.assertEqual(r.json()["ulasan"]["produk"]["id"], str(self.produk.pk))

    def test_produk_id_bukan_uuid(self):
        self.assertEqual(self.kirim(produk_id="12").status_code, 400)
        self.assertEqual(self.kirim(produk_id="").status_code, 400)

    def test_produk_tidak_ditemukan(self):
        self.assertEqual(self.kirim(produk_id=str(uuid.uuid4())).status_code, 404)

    def test_produk_milik_toko_lain(self):
        _, toko2 = buat_seller("rini", "Toko Rini")
        asing = buat_produk(toko2, "Tas Kain")
        self.assertEqual(self.kirim(produk_id=str(asing.pk)).status_code, 400)

    def test_ulasan_ganda_ditolak(self):
        self.assertEqual(self.kirim().status_code, 201)
        self.assertEqual(self.kirim().status_code, 409)

    def test_filter_daftar_berdasarkan_produk(self):
        lain = buat_produk(self.toko, "Sikat Gigi")
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, lain, 2)
        r = self.client.get(reverse("reviews:daftar", args=[self.toko.id]), {"produk": str(lain.pk)})
        data = r.json()
        self.assertEqual([u["rating"] for u in data["ulasan"]], [2])
        self.assertEqual(data["ringkasan_produk"]["rata_rata"], 2.0)
        self.assertEqual(len(data["produk"]), 2)

    def test_filter_produk_tidak_valid_diabaikan(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        r = self.client.get(reverse("reviews:daftar", args=[self.toko.id]), {"produk": "abc"})
        self.assertEqual(len(r.json()["ulasan"]), 1)
        self.assertIsNone(r.json()["ringkasan_produk"])


class IntegrasiTest(DasarTest):
    def test_ambil_produk(self):
        self.assertEqual(
            integrations.ambil_produk(self.produk.pk),
            {"nama": "Sedotan Bambu", "toko_id": self.toko.id},
        )
        self.assertIsNone(integrations.ambil_produk(uuid.uuid4()))

    def test_pernah_membeli_masih_stub(self):
        self.assertTrue(integrations.STUB_PEMBELIAN)
        self.assertTrue(integrations.pernah_membeli(self.b1, self.produk.pk))
