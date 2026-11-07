from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import FotoUlasan
from .tests import DasarTest, buat_produk, buat_ulasan


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
