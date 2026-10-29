import tempfile
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from apps.products.models import Product
from apps.users.models import SellerProfile
from apps.checkout.models import Order, OrderItem

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

    def buat_pesanan(self, status="selesai", quantity=2):
        order = Order.objects.create(
            buyer=self.buyer, seller=self.seller, store_name=self.seller.store_name,
            recipient_name="Pembeli", phone="08123456789", shipping_address="Bandung",
            status=status, total_price=100000 * quantity + 7000, shipping_cost=7000,
        )
        OrderItem.objects.create(
            order=order, product=self.produk, product_name=self.produk.name,
            price=100000, quantity=quantity,
        )
        return order

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

    def test_ringkasan_toko_memakai_data_transaksi_nyata(self):
        self.buat_pesanan("selesai", 2)
        self.buat_pesanan("diproses", 1)
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(reverse("dashboard:seller_summary"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["jumlah_produk"], 1)
        self.assertEqual(response.context["jumlah_pesanan"], 2)
        self.assertEqual(response.context["pendapatan_bulan"], 200000)
        self.assertEqual(response.context["produk_terlaris"][0]["terjual"], 2)
        self.assertContains(response, "Rp. 200.000")

    def test_laporan_mingguan_mengabaikan_pesanan_belum_selesai(self):
        self.buat_pesanan("selesai", 3)
        self.buat_pesanan("dikirim", 5)
        self.client.login(email="seller@gmail.com", password="pass")
        response = self.client.get(reverse("dashboard:sales_report"), {"periode": "mingguan"})
        self.assertEqual(response.status_code, 200)
        penjualan = response.context["penjualan"]
        self.assertEqual(penjualan["periode"], "mingguan")
        self.assertEqual(penjualan["pendapatan"], 300000)
        self.assertEqual(penjualan["rata_pesanan"], 300000)
        self.assertEqual(penjualan["produk_terlaris"][0]["terjual"], 3)
