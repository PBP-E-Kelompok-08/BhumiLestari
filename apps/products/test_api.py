import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.reviews.models import UlasanToko
from apps.users.models import SellerProfile

from .models import EcoFeature, Product


User = get_user_model()


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ProductPublicAPITest(TestCase):
    def setUp(self):
        self.seller_user = User.objects.create_user(
            username="seller-api",
            email="seller-api@example.com",
            password="password",
            role="seller",
        )
        self.other_seller_user = User.objects.create_user(
            username="seller-api-2",
            email="seller-api-2@example.com",
            password="password",
            role="seller",
        )
        self.buyer = User.objects.create_user(
            username="buyer-api",
            email="buyer-api@example.com",
            password="password",
            role="buyer",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko API",
        )
        self.other_seller = SellerProfile.objects.create(
            user=self.other_seller_user,
            store_name="Toko API Lain",
        )
        self.reusable, _ = EcoFeature.objects.get_or_create(name="Reusable")
        self.local, _ = EcoFeature.objects.get_or_create(name="Locally Sourced")

        self.verified = self._create_product(
            seller=self.seller,
            name="Tas Rotan Lestari",
            category="daily_supplies",
            price=100000,
            status="verified",
        )
        self.verified.eco_features.add(self.reusable, self.local)
        self.pending = self._create_product(
            seller=self.seller,
            name="Produk Menunggu",
            category="furniture",
            price=50000,
            status="pending",
        )
        self.other_verified = self._create_product(
            seller=self.other_seller,
            name="Meja Bambu",
            category="furniture",
            price=200000,
            status="verified",
        )
        self.other_verified.eco_features.add(self.local)

        self.list_url = reverse("products_api:list")

    def _create_product(self, seller, name, category, price, status):
        return Product.objects.create(
            seller=seller,
            name=name,
            description=f"Deskripsi {name}",
            category=category,
            materials="Rotan, Bambu",
            origin="Yogyakarta",
            price=price,
            discount=10,
            stock=5,
            image=SimpleUploadedFile(
                f"{name}.jpg",
                b"gambar",
                content_type="image/jpeg",
            ),
            verification_document=SimpleUploadedFile(
                f"{name}.pdf",
                b"dokumen rahasia",
                content_type="application/pdf",
            ),
            status=status,
        )

    def test_list_hanya_menampilkan_produk_verified(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        ids = {item["id"] for item in data["products"]}
        self.assertIn(str(self.verified.pk), ids)
        self.assertNotIn(str(self.pending.pk), ids)

    def test_serializer_tidak_mengekspos_dokumen_dan_data_user(self):
        item = self.client.get(
            reverse("products_api:detail", args=[self.verified.pk])
        ).json()["data"]

        self.assertNotIn("verification_document", item)
        self.assertNotIn("external_product_id", item)
        self.assertNotIn("user", item["seller"])
        self.assertNotIn("email", item["seller"])
        self.assertEqual(item["materials"], ["Rotan", "Bambu"])
        self.assertEqual(item["eco_features"], ["Locally Sourced", "Reusable"])
        self.assertEqual(item["price"], 100000)
        self.assertEqual(item["final_price"], 90000)
        self.assertTrue(item["image_url"].startswith("http://testserver/"))

    def test_filter_pencarian_kategori_seller_dan_eco_feature(self):
        query_cases = [
            ({"q": "rotan lestari"}, self.verified.pk),
            ({"category": "daily_supplies"}, self.verified.pk),
            ({"seller_id": self.other_seller.pk}, self.other_verified.pk),
            ({"eco_feature": "reusable"}, self.verified.pk),
        ]

        for query, expected_id in query_cases:
            with self.subTest(query=query):
                data = self.client.get(self.list_url, query).json()
                self.assertEqual(data["count"], 1)
                self.assertEqual(data["products"][0]["id"], str(expected_id))

    def test_filter_seller_tidak_valid_menghasilkan_daftar_kosong(self):
        response = self.client.get(self.list_url, {"seller_id": "bukan-angka"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    def test_urutan_harga(self):
        termurah = self.client.get(
            self.list_url,
            {"urut": "termurah"},
        ).json()["products"]
        termahal = self.client.get(
            self.list_url,
            {"urut": "termahal"},
        ).json()["products"]

        self.assertEqual(termurah[0]["id"], str(self.verified.pk))
        self.assertEqual(termahal[0]["id"], str(self.other_verified.pk))

    def test_rating_hanya_menghitung_ulasan_yang_tampil(self):
        UlasanToko.objects.create(
            toko=self.seller,
            pembeli=self.buyer,
            produk=self.verified,
            nama_produk=self.verified.name,
            rating=5,
        )
        hidden_buyer = User.objects.create_user(
            username="hidden-reviewer",
            email="hidden-reviewer@example.com",
            password="password",
        )
        UlasanToko.objects.create(
            toko=self.seller,
            pembeli=hidden_buyer,
            produk=self.verified,
            nama_produk=self.verified.name,
            rating=1,
            disembunyikan=True,
        )

        item = self.client.get(
            reverse("products_api:detail", args=[self.verified.pk])
        ).json()["data"]

        self.assertEqual(item["rating"], 5.0)
        self.assertEqual(item["review_count"], 1)

    def test_detail_produk_nonverified_tidak_dapat_diakses(self):
        response = self.client.get(
            reverse("products_api:detail", args=[self.pending.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_paginasi_membatasi_jumlah_produk(self):
        response = self.client.get(self.list_url, {"page_size": 1})

        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["products"]), 1)
        self.assertIsNotNone(data["next"])

    def test_daftar_eco_feature_diurutkan(self):
        response = self.client.get(reverse("products_api:eco-features"))

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["eco_features"]]
        self.assertEqual(names, sorted(names))
        self.assertIn("Locally Sourced", names)
        self.assertIn("Reusable", names)
