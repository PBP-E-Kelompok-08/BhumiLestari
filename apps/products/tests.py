import tempfile
import uuid
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.users.models import SellerProfile
from .models import Product
from .views import kirim_ke_api,cek_status
import requests
from unittest.mock import patch, MagicMock

User = get_user_model()


def buat_produk(seller, name="Tas Rotan"):
    return Product.objects.create(
        seller=seller,
        name=name,
        description="Tas dari rotan",
        category="daily_supplies",
        materials="Rotan, Bambu",
        origin="Yogyakarta",
        price=100000,
        image=SimpleUploadedFile("foto.jpg", b"jpg"),
        verification_document=SimpleUploadedFile("sertifikat.pdf", b"pdf"),
    )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProductTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user("seller1", email="seller1@gmail.com", password="pass", role="seller")
        self.user2 = User.objects.create_user("seller2", email="seller2@gmail.com", password="pass", role="seller")
        self.buyer = User.objects.create_user("buyer", email="buyer@gmail.com", password="pass", role="buyer")
        self.admin = User.objects.create_superuser("admin", "admin@gmail.com", "pass")

        self.seller1 = SellerProfile.objects.create(user=self.user1, store_name="Toko 1")
        self.seller2 = SellerProfile.objects.create(user=self.user2, store_name="Toko 2")

        self.produk = buat_produk(self.seller1)
        self.produk_lain = buat_produk(self.seller2, "Produk Seller 2")

        self.dashboard = reverse("dashboard:show_dashboard_home")

    def test_guest_diarahkan_ke_login(self):
        response = self.client.get(reverse("products:add_product"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_buyer_tidak_bisa_tambah_produk(self):
        self.client.login(username="buyer@gmail.com", password="pass")
        response = self.client.get(reverse("products:add_product"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard)

    def test_seller_tidak_bisa_edit_produk_orang_lain(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        response = self.client.get(reverse("products:edit_product", args=[self.produk_lain.pk]))
        self.assertEqual(response.status_code, 404)

    def test_seller_tidak_bisa_hapus_produk_orang_lain(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        response = self.client.post(reverse("products:delete_product", args=[self.produk_lain.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.produk_lain.pk).exists())

    def test_antrean_verifikasi_seller_ditolak(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        response = self.client.get(reverse("products:verification_queue"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.dashboard)

    def test_antrean_verifikasi_admin_boleh(self):
        self.client.login(username="admin@gmail.com", password="pass")
        response = self.client.get(reverse("products:verification_queue"))
        self.assertEqual(response.status_code, 200)

    def test_delete_menghapus_produk(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        self.client.post(reverse("products:delete_product", args=[self.produk.pk]))
        self.assertFalse(Product.objects.filter(pk=self.produk.pk).exists())

    def test_delete_lewat_get_tidak_menghapus(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        self.client.get(reverse("products:delete_product", args=[self.produk.pk]))
        self.assertTrue(Product.objects.filter(pk=self.produk.pk).exists())

    def test_admin_approve(self):
        self.client.login(username="admin@gmail.com", password="pass")
        url = reverse("products:review_product_admin", args=[self.produk.pk])
        self.client.post(url, {"action": "approve"})
        produk = Product.objects.get(pk=self.produk.pk)
        self.assertEqual(produk.status, "verified")

    def test_admin_reject(self):
        self.client.login(username="admin@gmail.com", password="pass")
        url = reverse("products:review_product_admin", args=[self.produk.pk])
        self.client.post(url, {"action": "reject", "reason": "Sertifikat buram"})
        produk = Product.objects.get(pk=self.produk.pk)
        self.assertEqual(produk.status, "rejected")
        self.assertEqual(produk.verification_summary, "Sertifikat buram")

    def test_non_admin_tidak_bisa_review(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        url = reverse("products:review_product_admin", args=[self.produk.pk])
        self.client.post(url, {"action": "approve"})
        produk = Product.objects.get(pk=self.produk.pk)
        self.assertEqual(produk.status, "pending")

    def test_filter_status_ngawur_tidak_error(self):
        self.client.login(username="admin@gmail.com", password="pass")
        response = self.client.get(reverse("products:verification_queue"), {"status": "abc"})
        self.assertEqual(response.status_code, 200)

    def test_model(self):
        self.assertEqual(str(self.produk), "Tas Rotan")
        self.assertEqual(self.produk.status, "pending")
        self.assertEqual(self.produk.seller, self.seller1)

    def test_harga_setelah_diskon(self):
        self.produk.discount = 25
        self.assertEqual(self.produk.final_price, 75000)

    def test_produk_tidak_ada_404(self):
        self.client.login(username="seller1@gmail.com", password="pass")
        response = self.client.get(reverse("products:edit_product", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)


    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.post")
    def test_kirim_ke_api_berhasil(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"data": {"product_id": "prd-001"}}
        mock_post.return_value = mock_response

        hasil = kirim_ke_api(self.produk)

        self.assertTrue(hasil)
        self.produk.refresh_from_db()
        self.assertEqual(self.produk.external_product_id, "prd-001")

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.post")
    def test_kirim_ke_api_status_bukan_201(self, mock_post):
        mock_post.return_value = MagicMock(status_code=400)

        hasil = kirim_ke_api(self.produk)
        self.assertFalse(hasil)

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.post")
    def test_kirim_ke_api_error_koneksi(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError()

        hasil = kirim_ke_api(self.produk)
        self.assertFalse(hasil)

    @patch("apps.products.views.kirim_ke_api")
    def test_cek_status_tanpa_external_id(self, mock_kirim):
        cek_status(self.produk)
        mock_kirim.assert_called_once_with(self.produk)

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.get")
    def test_cek_status_update_status(self, mock_get):
        self.produk.external_product_id = "prd-001"
        self.produk.save()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"verification": {"status": "verified", "summary": "Sesuai datanya"}}
        }
        mock_get.return_value = mock_response

        cek_status(self.produk)
        self.produk.refresh_from_db()
        self.assertEqual(self.produk.status, "verified")
        self.assertEqual(self.produk.verification_summary, "Sesuai datanya")

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.get")
    def test_cek_status_verification_kosong(self, mock_get):
        self.produk.external_product_id = "prd-001"
        self.produk.save()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"verification": None}}
        mock_get.return_value = mock_response

        cek_status(self.produk)
        self.produk.refresh_from_db()
        self.assertEqual(self.produk.status, "pending")

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.get")
    def test_cek_status_bukan_200(self, mock_get):
        self.produk.external_product_id = "prd-001"
        self.produk.save()
        mock_get.return_value = MagicMock(status_code=404)

        cek_status(self.produk)
        self.produk.refresh_from_db()
        self.assertEqual(self.produk.status, "pending")

    @override_settings(MOCK_API_BASE_URL="http://mock-api.test")
    @patch("apps.products.views.requests.get")
    def test_cek_status_error_koneksi(self, mock_get):
        self.produk.external_product_id = "prd-001"
        self.produk.save()
        mock_get.side_effect = requests.exceptions.ConnectionError()

        cek_status(self.produk)
        self.produk.refresh_from_db()
        self.assertEqual(self.produk.status, "pending")