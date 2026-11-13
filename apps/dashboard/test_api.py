import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.checkout.models import Order, OrderItem
from apps.products.models import Product
from apps.users.models import SellerProfile


User = get_user_model()


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SellerSummaryAPITest(TestCase):
    def setUp(self):
        self.seller_user = self._create_user("summary-seller", "seller")
        self.buyer = self._create_user("summary-buyer", "buyer")
        self.other_buyer = self._create_user("summary-other-buyer", "buyer")
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Ringkasan",
        )
        self.product = Product.objects.create(
            seller=self.seller,
            name="Produk Ringkasan",
            description="Produk untuk ringkasan seller",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=10000,
            stock=10,
            image=SimpleUploadedFile("produk.jpg", b"jpg"),
            verification_document=SimpleUploadedFile("dokumen.pdf", b"pdf"),
            status="verified",
        )
        self.url = reverse("dashboard_api:seller-summary")

    def _create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
            role=role,
        )

    def _create_order(self, status, quantity):
        order = Order.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            store_name=self.seller.store_name,
            recipient_name="Pembeli",
            phone="08123456789",
            shipping_address="Bandung",
            status=status,
            total_price=10000 * quantity + 7000,
            shipping_cost=7000,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name=self.product.name,
            price=10000,
            quantity=quantity,
        )
        return order

    def test_guest_dan_buyer_tidak_dapat_mengakses_ringkasan_seller(self):
        guest_response = self.client.get(self.url)
        self.client.force_login(self.buyer)
        buyer_response = self.client.get(self.url)

        self.assertEqual(guest_response.status_code, 403)
        self.assertEqual(buyer_response.status_code, 403)

    def test_seller_tanpa_profile_mendapatkan_not_found(self):
        seller_without_profile = self._create_user("no-profile", "seller")
        self.client.force_login(seller_without_profile)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_ringkasan_memakai_transaksi_selesai_tokonya(self):
        self._create_order("selesai", 2)
        self._create_order("diproses", 5)
        self.client.force_login(self.seller_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["store_name"], "Toko Ringkasan")
        self.assertEqual(data["product_count"], 1)
        self.assertEqual(data["order_count"], 2)
        self.assertEqual(data["monthly_revenue"], 20000)
        self.assertEqual(len(data["revenue_chart"]), 7)
        self.assertEqual(
            data["best_selling_products"][0]["units_sold"],
            2,
        )

    def test_ringkasan_tidak_mengandung_data_toko_lain(self):
        other_seller_user = self._create_user("other-summary-seller", "seller")
        other_seller = SellerProfile.objects.create(
            user=other_seller_user,
            store_name="Toko Lain",
        )
        other_product = Product.objects.create(
            seller=other_seller,
            name="Produk Toko Lain",
            description="Produk milik toko lain",
            category="daily_supplies",
            materials="Kayu",
            origin="Bogor",
            price=50000,
            stock=10,
            status="verified",
        )
        order = Order.objects.create(
            buyer=self.other_buyer,
            seller=other_seller,
            store_name=other_seller.store_name,
            recipient_name="Pembeli Lain",
            phone="08123456789",
            shipping_address="Bogor",
            status="selesai",
            total_price=500000,
        )
        OrderItem.objects.create(
            order=order,
            product=other_product,
            product_name=other_product.name,
            price=50000,
            quantity=10,
        )
        self._create_order("selesai", 1)
        self.client.force_login(self.seller_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["monthly_revenue"], 10000)
        self.assertEqual(data["order_count"], 1)
        self.assertEqual(len(data["best_selling_products"]), 1)


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SalesReportAPITest(TestCase):
    def setUp(self):
        self.seller_user = self._create_user("report-seller", "seller")
        self.other_seller_user = self._create_user(
            "report-other-seller",
            "seller",
        )
        self.buyer = self._create_user("report-buyer", "buyer")
        self.admin = User.objects.create_superuser(
            username="report-admin",
            email="report-admin@example.com",
            password="password",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Laporan",
        )
        self.other_seller = SellerProfile.objects.create(
            user=self.other_seller_user,
            store_name="Toko Laporan Lain",
        )
        self.product = self._create_product(
            self.seller,
            "Produk Laporan",
            10000,
        )
        self.other_product = self._create_product(
            self.other_seller,
            "Produk Laporan Lain",
            50000,
        )
        self.url = reverse("dashboard_api:sales-report")

    def _create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
            role=role,
        )

    def _create_product(self, seller, name, price):
        return Product.objects.create(
            seller=seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=price,
            stock=10,
            status="verified",
        )

    def _create_order(self, seller, product, status, quantity):
        order = Order.objects.create(
            buyer=self.buyer,
            seller=seller,
            store_name=seller.store_name,
            recipient_name="Pembeli",
            phone="08123456789",
            shipping_address="Bandung",
            status=status,
            total_price=int(product.price) * quantity,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            price=int(product.price),
            quantity=quantity,
        )
        return order

    def test_guest_dan_buyer_tidak_dapat_mengakses_laporan(self):
        guest_response = self.client.get(self.url)
        self.client.force_login(self.buyer)
        buyer_response = self.client.get(self.url)

        self.assertEqual(guest_response.status_code, 403)
        self.assertEqual(buyer_response.status_code, 403)

    def test_periode_tidak_valid_ditolak(self):
        self.client.force_login(self.seller_user)

        response = self.client.get(self.url, {"period": "tahunan"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("period", response.json())

    def test_seller_tanpa_profile_mendapatkan_not_found(self):
        seller_without_profile = self._create_user("report-no-profile", "seller")
        self.client.force_login(seller_without_profile)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_seller_hanya_melihat_laporan_tokonya(self):
        self._create_order(self.seller, self.product, "selesai", 2)
        self._create_order(self.seller, self.product, "dikirim", 5)
        self._create_order(
            self.other_seller,
            self.other_product,
            "selesai",
            10,
        )
        self.client.force_login(self.seller_user)

        response = self.client.get(self.url, {"period": "mingguan"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["role"], "seller")
        self.assertEqual(data["period"], "mingguan")
        self.assertEqual(data["revenue"], 20000)
        self.assertEqual(data["average_order_value"], 20000)
        self.assertEqual(data["best_selling_products"][0]["units_sold"], 2)

    def test_admin_melihat_agregasi_seluruh_toko(self):
        self._create_order(self.seller, self.product, "selesai", 2)
        self._create_order(
            self.other_seller,
            self.other_product,
            "selesai",
            10,
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.url, {"period": "mingguan"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["role"], "admin")
        self.assertEqual(data["revenue"], 520000)
        self.assertEqual(data["average_order_value"], 260000)
        self.assertEqual(len(data["best_selling_products"]), 2)

    def test_periode_default_adalah_bulanan(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["period"], "bulanan")
