import io
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.checkout.models import Order, OrderItem
from .models import BalasanUlasan, FotoUlasan, LaporanUlasan, UlasanToko
from .tests import DasarTest, buat_admin, buat_produk, buat_seller, buat_ulasan, tua


class DaftarUlasanTokoAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        self.url = reverse("reviews_api:daftar-toko", args=[self.toko.id])

    def test_guest_mendapat_nama_samaran_dan_foto_terkunci(self):
        ulasan = buat_ulasan(self.toko, self.b1, self.produk, 5, komentar="Bagus")
        FotoUlasan.objects.create(
            ulasan=ulasan,
            gambar=SimpleUploadedFile("foto.png", b"isi-foto", content_type="image/png"),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertNotEqual(data["ulasan"][0]["pembeli"], self.b1.full_name)
        self.assertEqual(data["ulasan"][0]["foto"], [])
        self.assertEqual(data["ulasan"][0]["jumlah_foto"], 1)
        self.assertTrue(data["ulasan"][0]["foto_terkunci"])

    def test_pengguna_login_mendapat_nama_dan_url_foto(self):
        ulasan = buat_ulasan(self.toko, self.b1, self.produk, 4)
        FotoUlasan.objects.create(
            ulasan=ulasan,
            gambar=SimpleUploadedFile("foto.png", b"isi-foto", content_type="image/png"),
        )
        self.client.force_login(self.b2)

        data = self.client.get(self.url).json()["ulasan"][0]

        self.assertEqual(data["pembeli"], self.b1.full_name)
        self.assertTrue(data["foto"][0].startswith("http://testserver/"))
        self.assertFalse(data["foto_terkunci"])

    def test_ulasan_disembunyikan_tidak_ditampilkan(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, self.produk, 1, disembunyikan=True)

        data = self.client.get(self.url).json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["ringkasan"]["total"], 1)

    def test_filter_rating_dan_urutan(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        produk_lain = self.produk
        ulasan_lain = buat_ulasan(self.toko, self.b2, produk_lain, 2)
        # Constraint satu ulasan per pembeli-produk tetap terpenuhi karena pembelinya berbeda.
        self.assertIsNotNone(ulasan_lain.pk)

        data = self.client.get(self.url, {"rating": "2", "urut": "terendah"}).json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["ulasan"][0]["rating"], 2)

    def test_toko_tidak_ditemukan(self):
        response = self.client.get(reverse("reviews_api:daftar-toko", args=[999999]))

        self.assertEqual(response.status_code, 404)


class DaftarUlasanSayaAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        self.url = reverse("reviews_api:daftar-saya")

    def test_guest_mendapat_error_permission_tanpa_redirect(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response.headers)

    def test_hanya_menampilkan_ulasan_milik_pengguna(self):
        ulasan_saya = buat_ulasan(self.toko, self.b1, self.produk, 5)
        buat_ulasan(self.toko, self.b2, self.produk, 2)
        self.client.force_login(self.b1)

        data = self.client.get(self.url).json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["ulasan"][0]["id"], ulasan_saya.id)
        self.assertTrue(data["ulasan"][0]["milik_saya"])
        self.assertTrue(data["ulasan"][0]["bisa_dihapus"])

    def test_pemilik_tetap_melihat_ulasan_yang_disembunyikan(self):
        ulasan = buat_ulasan(
            self.toko,
            self.b1,
            self.produk,
            1,
            disembunyikan=True,
        )
        self.client.force_login(self.b1)

        data = self.client.get(self.url).json()

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["ulasan"][0]["id"], ulasan.id)
        self.assertTrue(data["ulasan"][0]["disembunyikan"])
        self.assertFalse(data["ulasan"][0]["bisa_diedit"])

    def test_pagination_dapat_diatur(self):
        buat_ulasan(self.toko, self.b1, self.produk, 5)
        produk_lain = buat_produk(self.toko, "Produk Kedua")
        buat_ulasan(self.toko, self.b1, produk_lain, 4)
        self.client.force_login(self.b1)

        data = self.client.get(self.url, {"page_size": 1}).json()

        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["ulasan"]), 1)
        self.assertIsNotNone(data["next"])


class TambahUlasanAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        self.url = reverse("reviews_api:daftar-toko", args=[self.toko.id])
        self.client.force_login(self.b1)
        self.order = Order.objects.create(
            buyer=self.b1,
            seller=self.toko,
            store_name=self.toko.store_name,
            recipient_name="Budi",
            phone="08123456789",
            shipping_address="Bandung",
            status="selesai",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.produk,
            product_name=self.produk.name,
            price=10000,
            quantity=1,
        )

    def payload(self, **perubahan):
        data = {
            "produk_id": str(self.produk.pk),
            "rating": 5,
            "komentar": "Produk sangat bagus",
        }
        data.update(perubahan)
        return data

    def test_pembeli_dapat_membuat_ulasan(self):
        response = self.client.post(self.url, self.payload(), content_type="application/json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(UlasanToko.objects.count(), 1)
        ulasan = UlasanToko.objects.get()
        self.assertEqual(ulasan.pembeli, self.b1)
        self.assertEqual(ulasan.produk, self.produk)
        self.assertEqual(response.json()["ulasan"]["produk"]["id"], str(self.produk.pk))

    def test_guest_ditolak_tanpa_redirect(self):
        self.client.logout()

        response = self.client.post(self.url, self.payload(), content_type="application/json")

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response.headers)

    def test_penjual_tidak_dapat_membuat_ulasan(self):
        self.client.force_login(self.seller_user)

        response = self.client.post(self.url, self.payload(), content_type="application/json")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UlasanToko.objects.exists())

    def test_pembelian_yang_belum_selesai_ditolak(self):
        self.order.status = "diproses"
        self.order.save(update_fields=["status"])

        response = self.client.post(self.url, self.payload(), content_type="application/json")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UlasanToko.objects.exists())

    def test_produk_toko_lain_ditolak(self):
        _, toko_lain = buat_seller("seller-lain", "Toko Lain")
        produk_lain = buat_produk(toko_lain, "Produk Toko Lain")

        response = self.client.post(
            self.url,
            self.payload(produk_id=str(produk_lain.pk)),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(UlasanToko.objects.exists())

    def test_ulasan_ganda_menghasilkan_conflict(self):
        self.assertEqual(
            self.client.post(self.url, self.payload(), content_type="application/json").status_code,
            201,
        )

        response = self.client.post(self.url, self.payload(), content_type="application/json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(UlasanToko.objects.count(), 1)

    def test_rating_tidak_valid_ditolak_serializer(self):
        response = self.client.post(
            self.url,
            self.payload(rating=6),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("rating", response.json())

    def test_foto_valid_disimpan(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), (255, 255, 255)).save(buffer, format="PNG")
        foto = SimpleUploadedFile("foto.png", buffer.getvalue(), content_type="image/png")

        response = self.client.post(self.url, self.payload(foto=[foto]))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(FotoUlasan.objects.count(), 1)

    def test_foto_palsu_ditolak(self):
        foto = SimpleUploadedFile("foto.png", b"bukan-gambar", content_type="image/png")

        response = self.client.post(self.url, self.payload(foto=[foto]))

        self.assertEqual(response.status_code, 400)
        self.assertIn("foto", response.json())


class UbahHapusUlasanAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        self.ulasan = buat_ulasan(
            self.toko,
            self.b1,
            self.produk,
            3,
            komentar="Komentar awal",
        )
        self.url = reverse("reviews_api:detail", args=[self.ulasan.pk])
        self.client.force_login(self.b1)

    def test_pemilik_dapat_mengubah_sebagian_data(self):
        response = self.client.patch(
            self.url,
            {"rating": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.ulasan.refresh_from_db()
        self.assertEqual(self.ulasan.rating, 5)
        self.assertEqual(self.ulasan.komentar, "Komentar awal")
        self.assertTrue(self.ulasan.diedit)

    def test_guest_ditolak_tanpa_redirect(self):
        self.client.logout()

        response = self.client.patch(
            self.url,
            {"rating": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response.headers)

    def test_pengguna_lain_tidak_dapat_mengedit(self):
        self.client.force_login(self.b2)

        response = self.client.patch(
            self.url,
            {"komentar": "Diubah orang lain"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.ulasan.refresh_from_db()
        self.assertEqual(self.ulasan.komentar, "Komentar awal")

    def test_ulasan_disembunyikan_tidak_dapat_diedit(self):
        self.ulasan.disembunyikan = True
        self.ulasan.save(update_fields=["disembunyikan"])

        response = self.client.patch(
            self.url,
            {"rating": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_ulasan_lebih_dari_tujuh_hari_tidak_dapat_diedit(self):
        tua(self.ulasan, 8)

        response = self.client.patch(
            self.url,
            {"rating": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_rating_tidak_valid_ditolak(self):
        response = self.client.patch(
            self.url,
            {"rating": 0},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("rating", response.json())

    def test_payload_kosong_ditolak(self):
        response = self.client.patch(self.url, {}, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.json())

    def test_pemilik_dapat_menghapus_ulasan(self):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UlasanToko.objects.filter(pk=self.ulasan.pk).exists())

    def test_pengguna_lain_tidak_dapat_menghapus(self):
        self.client.force_login(self.b2)

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(UlasanToko.objects.filter(pk=self.ulasan.pk).exists())

    def test_admin_dapat_menghapus_ulasan(self):
        self.client.force_login(buat_admin())

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(UlasanToko.objects.filter(pk=self.ulasan.pk).exists())

    def test_ulasan_tidak_ditemukan(self):
        response = self.client.patch(
            reverse("reviews_api:detail", args=[999999]),
            {"rating": 5},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)


class BalasanUlasanAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.ulasan = buat_ulasan(self.toko, self.b1, self.produk, 5)
        self.url = reverse("reviews_api:balasan", args=[self.ulasan.pk])
        self.client.force_login(self.seller_user)

    def buat_balasan(self, pesan="Terima kasih atas ulasannya"):
        return BalasanUlasan.objects.create(
            ulasan=self.ulasan,
            penjual=self.seller_user,
            pesan=pesan,
        )

    def test_pemilik_toko_dapat_membalas(self):
        response = self.client.post(
            self.url,
            {"pesan": "Terima kasih"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BalasanUlasan.objects.get().pesan, "Terima kasih")
        self.assertEqual(response.json()["balasan"]["pesan"], "Terima kasih")

    def test_guest_ditolak_tanpa_redirect(self):
        self.client.logout()

        response = self.client.post(
            self.url,
            {"pesan": "Terima kasih"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response.headers)

    def test_penjual_lain_tidak_dapat_membalas(self):
        user_lain, _ = buat_seller("penjual-lain", "Toko Penjual Lain")
        self.client.force_login(user_lain)

        response = self.client.post(
            self.url,
            {"pesan": "Balasan ilegal"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BalasanUlasan.objects.exists())

    def test_ulasan_disembunyikan_tidak_dapat_dibalas(self):
        self.ulasan.disembunyikan = True
        self.ulasan.save(update_fields=["disembunyikan"])

        response = self.client.post(
            self.url,
            {"pesan": "Terima kasih"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_balasan_ganda_menghasilkan_conflict(self):
        self.buat_balasan()

        response = self.client.post(
            self.url,
            {"pesan": "Balasan kedua"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(BalasanUlasan.objects.count(), 1)

    def test_pesan_kosong_ditolak(self):
        response = self.client.post(
            self.url,
            {"pesan": ""},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("pesan", response.json())

    def test_pemilik_toko_dapat_mengedit_balasan(self):
        balasan = self.buat_balasan("Balasan awal")

        response = self.client.patch(
            self.url,
            {"pesan": "Balasan diperbarui"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        balasan.refresh_from_db()
        self.assertEqual(balasan.pesan, "Balasan diperbarui")

    def test_balasan_lebih_dari_satu_hari_tidak_dapat_diedit(self):
        balasan = self.buat_balasan()
        BalasanUlasan.objects.filter(pk=balasan.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )

        response = self.client.patch(
            self.url,
            {"pesan": "Terlambat diedit"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_pemilik_toko_dapat_menghapus_balasan(self):
        self.buat_balasan()

        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(BalasanUlasan.objects.exists())

    def test_balasan_belum_ada_menghasilkan_not_found(self):
        response = self.client.patch(
            self.url,
            {"pesan": "Belum tersedia"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)


class LaporanUlasanAPITest(DasarTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.ulasan = buat_ulasan(self.toko, self.b1, self.produk, 2)
        self.url = reverse("reviews_api:laporan", args=[self.ulasan.pk])
        self.client.force_login(self.seller_user)

    def test_pemilik_toko_dapat_melaporkan_ulasan(self):
        response = self.client.post(
            self.url,
            {"alasan": "Komentar mengandung informasi tidak benar"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        laporan = LaporanUlasan.objects.get()
        self.assertEqual(laporan.pelapor, self.seller_user)
        self.assertEqual(laporan.status, LaporanUlasan.STATUS_MENUNGGU)
        self.assertEqual(response.json()["status"], "menunggu")

    def test_guest_ditolak_tanpa_redirect(self):
        self.client.logout()

        response = self.client.post(
            self.url,
            {"alasan": "Komentar tidak sesuai"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Location", response.headers)

    def test_penjual_lain_tidak_dapat_melaporkan(self):
        user_lain, _ = buat_seller("pelapor-lain", "Toko Pelapor Lain")
        self.client.force_login(user_lain)

        response = self.client.post(
            self.url,
            {"alasan": "Komentar tidak sesuai"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(LaporanUlasan.objects.exists())

    def test_ulasan_disembunyikan_tidak_dapat_dilaporkan(self):
        self.ulasan.disembunyikan = True
        self.ulasan.save(update_fields=["disembunyikan"])

        response = self.client.post(
            self.url,
            {"alasan": "Komentar tidak sesuai"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_laporan_ganda_menghasilkan_conflict(self):
        LaporanUlasan.objects.create(
            ulasan=self.ulasan,
            pelapor=self.seller_user,
            alasan="Laporan pertama",
        )

        response = self.client.post(
            self.url,
            {"alasan": "Laporan kedua"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(LaporanUlasan.objects.count(), 1)

    def test_alasan_terlalu_pendek_ditolak(self):
        response = self.client.post(
            self.url,
            {"alasan": "spam"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("alasan", response.json())

    def test_request_keenam_dibatasi_throttle(self):
        for _ in range(5):
            response = self.client.post(
                self.url,
                {"alasan": "x"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)

        response = self.client.post(
            self.url,
            {"alasan": "Alasan yang valid"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 429)
