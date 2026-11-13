import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.reviews.models import UlasanToko
from apps.users.models import SellerProfile

from .models import EcoFeature, Product


User = get_user_model()


def valid_png(name="product.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color="green").save(buffer, format="PNG")
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="image/png",
    )


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


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ProductSellerAPITest(TestCase):
    def setUp(self):
        self.seller_user = User.objects.create_user(
            username="seller-owner",
            email="seller-owner@example.com",
            password="password",
            role="seller",
        )
        self.other_seller_user = User.objects.create_user(
            username="seller-other",
            email="seller-other@example.com",
            password="password",
            role="seller",
        )
        self.buyer = User.objects.create_user(
            username="buyer-products",
            email="buyer-products@example.com",
            password="password",
            role="buyer",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Owner",
        )
        self.other_seller = SellerProfile.objects.create(
            user=self.other_seller_user,
            store_name="Toko Other",
        )
        self.feature, _ = EcoFeature.objects.get_or_create(name="Reusable")
        self.own_product = self._create_product(self.seller, "Produk Sendiri")
        self.other_product = self._create_product(
            self.other_seller,
            "Produk Orang Lain",
        )
        self.url = reverse("products_api:mine")
        self.detail_url = reverse(
            "products_api:mine-detail",
            args=[self.own_product.pk],
        )

    def _create_product(self, seller, name):
        product = Product.objects.create(
            seller=seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=50000,
            stock=3,
            image=SimpleUploadedFile(f"{name}.jpg", b"gambar"),
            verification_document=SimpleUploadedFile(
                f"{name}.pdf",
                b"%PDF-dokumen",
            ),
            status="pending",
        )
        product.eco_features.add(self.feature)
        return product

    def _create_payload(self, name="Produk Mobile"):
        return {
            "name": name,
            "description": "Produk ramah lingkungan dari aplikasi mobile",
            "category": "daily_supplies",
            "materials": "Bambu, Kayu",
            "origin": "Bandung",
            "eco_feature_ids": [self.feature.pk],
            "price": 75000,
            "discount": 10,
            "stock": 8,
            "image": valid_png(),
            "verification_document": SimpleUploadedFile(
                "sertifikat.pdf",
                b"%PDF-1.4 dokumen",
                content_type="application/pdf",
            ),
        }

    def test_guest_dan_buyer_tidak_dapat_mengakses_endpoint_seller(self):
        guest_response = self.client.get(self.url)
        self.client.force_login(self.buyer)
        buyer_response = self.client.get(self.url)

        self.assertEqual(guest_response.status_code, 403)
        self.assertEqual(buyer_response.status_code, 403)

    def test_seller_hanya_mendapat_produk_milik_sendiri(self):
        self.client.force_login(self.seller_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["products"][0]["id"], str(self.own_product.pk))
        self.assertNotEqual(data["products"][0]["id"], str(self.other_product.pk))

    def test_seller_dapat_memfilter_status(self):
        self.own_product.status = "verified"
        self.own_product.save(update_fields=["status"])
        self.client.force_login(self.seller_user)

        found = self.client.get(self.url, {"status": "verified"}).json()
        empty = self.client.get(self.url, {"status": "pending"}).json()

        self.assertEqual(found["count"], 1)
        self.assertEqual(empty["count"], 0)

    @patch("apps.products.api_views.kirim_ke_api", return_value=True)
    def test_seller_dapat_membuat_produk(self, mock_sync):
        self.client.force_login(self.seller_user)

        response = self.client.post(self.url, self._create_payload())

        self.assertEqual(response.status_code, 201)
        data = response.json()
        product = Product.objects.get(name="Produk Mobile")
        self.assertEqual(product.seller, self.seller)
        self.assertEqual(product.status, "pending")
        self.assertEqual(list(product.eco_features.all()), [self.feature])
        self.assertTrue(data["mock_api_synced"])
        self.assertNotIn("verification_document", data["product"])
        self.assertTrue(data["product"]["verification_document_uploaded"])
        mock_sync.assert_called_once_with(product)

    @patch("apps.products.api_views.kirim_ke_api", return_value=False)
    def test_produk_tetap_disimpan_saat_mock_api_gagal(self, mock_sync):
        self.client.force_login(self.seller_user)

        response = self.client.post(
            self.url,
            self._create_payload(name="Produk Belum Sinkron"),
        )

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["mock_api_synced"])
        self.assertTrue(Product.objects.filter(name="Produk Belum Sinkron").exists())
        mock_sync.assert_called_once()

    @patch("apps.products.api_views.kirim_ke_api")
    def test_dokumen_tidak_valid_ditolak(self, mock_sync):
        self.client.force_login(self.seller_user)
        payload = self._create_payload(name="Produk Dokumen Palsu")
        payload["verification_document"] = SimpleUploadedFile(
            "sertifikat.pdf",
            b"bukan pdf",
            content_type="application/pdf",
        )

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("verification_document", response.json())
        self.assertFalse(Product.objects.filter(name="Produk Dokumen Palsu").exists())
        mock_sync.assert_not_called()

    def test_detail_hanya_dapat_mengakses_produk_milik_sendiri(self):
        self.client.force_login(self.seller_user)

        own_response = self.client.get(self.detail_url)
        other_response = self.client.get(
            reverse("products_api:mine-detail", args=[self.other_product.pk])
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(
            own_response.json()["product"]["id"],
            str(self.own_product.pk),
        )
        self.assertEqual(other_response.status_code, 404)

    @patch("apps.products.api_views.kirim_ke_api")
    def test_patch_nonverifikasi_tidak_mengubah_status(self, mock_sync):
        self.own_product.status = "verified"
        self.own_product.save(update_fields=["status"])
        self.client.force_login(self.seller_user)

        response = self.client.patch(
            self.detail_url,
            {"name": "Nama Produk Baru", "stock": 10},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.own_product.refresh_from_db()
        self.assertEqual(self.own_product.name, "Nama Produk Baru")
        self.assertEqual(self.own_product.stock, 10)
        self.assertEqual(self.own_product.status, "verified")
        self.assertFalse(response.json()["verification_resubmitted"])
        self.assertIsNone(response.json()["mock_api_synced"])
        mock_sync.assert_not_called()

    @patch("apps.products.api_views.kirim_ke_api", return_value=True)
    def test_patch_data_verifikasi_mengembalikan_status_pending(self, mock_sync):
        self.own_product.status = "verified"
        self.own_product.verification_summary = "Lolos"
        self.own_product.external_product_id = "prd-001"
        self.own_product.save(
            update_fields=[
                "status",
                "verification_summary",
                "external_product_id",
            ]
        )
        self.client.force_login(self.seller_user)

        response = self.client.patch(
            self.detail_url,
            {"origin": "Yogyakarta"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.own_product.refresh_from_db()
        self.assertEqual(self.own_product.origin, "Yogyakarta")
        self.assertEqual(self.own_product.status, "pending")
        self.assertEqual(self.own_product.verification_summary, "")
        self.assertTrue(response.json()["verification_resubmitted"])
        self.assertTrue(response.json()["mock_api_synced"])
        mock_sync.assert_called_once_with(self.own_product)

    @patch("apps.products.api_views.kirim_ke_api")
    def test_status_tidak_dapat_diubah_langsung_oleh_seller(self, mock_sync):
        self.client.force_login(self.seller_user)

        response = self.client.patch(
            self.detail_url,
            {"status": "verified"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.own_product.refresh_from_db()
        self.assertEqual(self.own_product.status, "pending")
        mock_sync.assert_not_called()

    def test_delete_hanya_menghapus_produk_milik_sendiri(self):
        self.client.force_login(self.seller_user)

        other_response = self.client.delete(
            reverse("products_api:mine-detail", args=[self.other_product.pk])
        )
        own_response = self.client.delete(self.detail_url)

        self.assertEqual(other_response.status_code, 404)
        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(own_response.json()["deleted_id"], str(self.own_product.pk))
        self.assertFalse(Product.objects.filter(pk=self.own_product.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.other_product.pk).exists())


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ProductVerificationAdminAPITest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-products-api",
            email="admin-products-api@example.com",
            password="password",
        )
        self.seller_user = User.objects.create_user(
            username="seller-verification",
            email="seller-verification@example.com",
            password="password",
            role="seller",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Verifikasi",
        )
        self.feature, _ = EcoFeature.objects.get_or_create(name="Reusable")
        self.pending = self._create_product("Produk Pending", "pending")
        self.verified = self._create_product("Produk Verified", "verified")
        self.queue_url = reverse("products_api:verification-queue")
        self.detail_url = reverse(
            "products_api:verification-detail",
            args=[self.pending.pk],
        )

    def _create_product(self, name, status):
        product = Product.objects.create(
            seller=self.seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=50000,
            stock=3,
            image=SimpleUploadedFile(f"{name}.jpg", b"gambar"),
            verification_document=SimpleUploadedFile(
                f"{name}.pdf",
                b"%PDF-dokumen rahasia",
            ),
            status=status,
        )
        product.eco_features.add(self.feature)
        return product

    def test_antrean_hanya_dapat_diakses_admin(self):
        guest_response = self.client.get(self.queue_url)
        self.client.force_login(self.seller_user)
        seller_response = self.client.get(self.queue_url)

        self.assertEqual(guest_response.status_code, 403)
        self.assertEqual(seller_response.status_code, 403)

    def test_admin_mendapat_antrean_filter_dan_ringkasan(self):
        self.client.force_login(self.admin)

        all_data = self.client.get(self.queue_url).json()
        pending_data = self.client.get(
            self.queue_url,
            {"status": "pending"},
        ).json()

        self.assertEqual(all_data["count"], 2)
        self.assertEqual(all_data["summary"]["pending"], 1)
        self.assertEqual(all_data["summary"]["verified"], 1)
        self.assertEqual(pending_data["count"], 1)
        self.assertEqual(pending_data["products"][0]["id"], str(self.pending.pk))

    def test_detail_admin_tidak_mengekspos_dokumen(self):
        self.client.force_login(self.admin)

        data = self.client.get(self.detail_url).json()["product"]

        self.assertNotIn("verification_document", data)
        self.assertTrue(data["verification_document_uploaded"])

    def test_admin_dapat_menyetujui_produk(self):
        self.client.force_login(self.admin)

        response = self.client.patch(
            self.detail_url,
            {"action": "approve"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "verified")
        self.assertEqual(self.pending.verification_summary, "")

    def test_penolakan_memerlukan_alasan(self):
        self.client.force_login(self.admin)

        invalid_response = self.client.patch(
            self.detail_url,
            {"action": "reject"},
            content_type="application/json",
        )
        valid_response = self.client.patch(
            self.detail_url,
            {"action": "reject", "reason": "Dokumen tidak terbaca"},
            content_type="application/json",
        )

        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("reason", invalid_response.json())
        self.assertEqual(valid_response.status_code, 200)
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, "rejected")
        self.assertEqual(self.pending.verification_summary, "Dokumen tidak terbaca")

    def test_produk_tidak_ditemukan(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("products_api:verification-detail", args=["00000000-0000-0000-0000-000000000000"])
        )

        self.assertEqual(response.status_code, 404)
