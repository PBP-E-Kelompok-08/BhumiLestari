import tempfile
import uuid
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.users.models import SellerProfile
from .models import Product

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