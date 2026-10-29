import tempfile
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.products.models import Product
from apps.users.models import SellerProfile

User = get_user_model()

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DashboardTest(TestCase):
    def setUp(self):
        self.seller_user = User.objects.create_user("seller", email="seller@gmail.com", password="pass", role="seller")
        self.buyer = User.objects.create_user("buyer", email="buyer@gmail.com", password="pass", role="buyer")
        self.admin = User.objects.create_superuser("admin", "test123@gmail.com", "pass")
        self.seller = SellerProfile.objects.create(user=self.seller_user, store_name="Toko Rara")

        self.produk = Product.objects.create(
            seller=self.seller,
            name="Tas Rotan Neo Series",
            description="Tas dari rotan",
            category="daily_supplies",
            materials="Rotan",
            origin="Yogyakarta",
            price=100000,
            image=SimpleUploadedFile("foto.jpg", b"jpg"),
            verification_document=SimpleUploadedFile("sertifikat.pdf", b"pdf"),
        )

        self.produk.status = "verified"
        self.produk.save()

        self.url_home = reverse("dashboard:show_dashboard_home")
        self.url_api = reverse("dashboard:api_products")

    def test_dashboard_guest(self):
        response = self.client.get(self.url_home)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_home.html")

    def test_dashboard_seller(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_home)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_home.html")

    def test_dashboard_buyer(self):
        self.client.login(email="buyer@gmail.com", password="pass")
        response = self.client.get(self.url_home)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_home.html")

    def test_dashboard_admin(self):
        self.client.login(email="test123@gmail.com", password="pass")
        response = self.client.get(self.url_home)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard_home.html")

    def test_seller_melihat_tombol_tambah_produk(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_home)
        self.assertContains(response, "Tambah Produk")

    def test_buyer_tidak_lihat_tombol_tambah_produk(self):
        self.client.login(email="buyer@gmail.com", password="pass")
        response = self.client.get(self.url_home)
        self.assertNotContains(response, "Tambah Produk")


    def test_api_products_status_dan_json(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_api)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_api_products_menampilkan_produk(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_api)
        self.assertContains(response, "Tas Rotan Neo Series")

    def test_api_products_search_ada_hasil(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_api, {"q": "Tas"})
        self.assertContains(response, "Tas Rotan Neo Series")

    def test_api_products_search_tidak_ada_hasil(self):
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(self.url_api, {"q": "ulululala"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Tas Rotan Neo Series")

    def test_api_products_guest(self):
        response = self.client.get(self.url_api)
        self.assertIn(response.status_code, [200, 302])