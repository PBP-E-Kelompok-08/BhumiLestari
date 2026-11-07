import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.checkout.models import Order, OrderItem
from .models import FotoUlasan, UlasanToko
from .tests import DasarTest, buat_produk, buat_seller, buat_ulasan


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
