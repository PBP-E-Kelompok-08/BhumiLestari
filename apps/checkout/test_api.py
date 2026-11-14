from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.products.models import Product
from apps.users.models import SellerProfile

from .models import Cart, CartItem, Order, OrderItem


User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class CartAPITest(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username="cart-buyer",
            email="cart-buyer@example.com",
            password="password",
            role="buyer",
        )
        self.other_buyer = User.objects.create_user(
            username="cart-other-buyer",
            email="cart-other-buyer@example.com",
            password="password",
            role="buyer",
        )
        self.seller_user = User.objects.create_user(
            username="cart-seller",
            email="cart-seller@example.com",
            password="password",
            role="seller",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Cart",
        )
        self.product = self._create_product(
            "Produk Cart",
            status="verified",
            stock=3,
        )
        self.pending_product = self._create_product(
            "Produk Pending",
            status="pending",
            stock=5,
        )
        self.cart_url = reverse("checkout_api:cart")
        self.create_url = reverse("checkout_api:item-create")

    def _create_product(self, name, status, stock):
        return Product.objects.create(
            seller=self.seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=10000,
            discount=10,
            stock=stock,
            status=status,
        )

    def test_cart_hanya_dapat_diakses_buyer(self):
        guest_response = self.client.get(self.cart_url)
        self.client.force_login(self.seller_user)
        seller_response = self.client.get(self.cart_url)

        self.assertEqual(guest_response.status_code, 403)
        self.assertEqual(seller_response.status_code, 403)

    def test_cart_kosong(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.cart_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])
        self.assertEqual(response.json()["cart_count"], 0)
        self.assertEqual(response.json()["selected_total"], 0)

    def test_tambah_dan_increment_item(self):
        self.client.force_login(self.buyer)

        first = self.client.post(
            self.create_url,
            {"product_id": str(self.product.pk), "quantity": 1},
            content_type="application/json",
        )
        second = self.client.post(
            self.create_url,
            {"product_id": str(self.product.pk), "quantity": 1},
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(CartItem.objects.get().quantity, 2)
        self.assertEqual(second.json()["cart_count"], 2)
        self.assertEqual(second.json()["item"]["line_total"], 18000)
        product_data = second.json()["item"]["product"]
        self.assertNotIn("verification_document", product_data)
        self.assertNotIn("email", product_data["seller"])

    def test_produk_nonverified_ditolak(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            self.create_url,
            {"product_id": str(self.pending_product.pk)},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_id", response.json())

    def test_tambah_melebihi_stok_ditolak(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            self.create_url,
            {"product_id": str(self.product.pk), "quantity": 4},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(CartItem.objects.exists())

    def test_patch_quantity_dan_selection(self):
        cart = Cart.objects.create(user=self.buyer)
        item = CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=1,
        )
        self.client.force_login(self.buyer)

        response = self.client.patch(
            reverse("checkout_api:item-detail", args=[item.pk]),
            {"quantity": 2, "is_selected": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)
        self.assertTrue(item.is_selected)
        self.assertEqual(response.json()["selected_count"], 2)
        self.assertEqual(response.json()["selected_total"], 18000)

    def test_tidak_dapat_mengubah_item_buyer_lain(self):
        foreign_cart = Cart.objects.create(user=self.other_buyer)
        foreign_item = CartItem.objects.create(
            cart=foreign_cart,
            product=self.product,
            quantity=1,
        )
        self.client.force_login(self.buyer)

        response = self.client.patch(
            reverse("checkout_api:item-detail", args=[foreign_item.pk]),
            {"quantity": 2},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        foreign_item.refresh_from_db()
        self.assertEqual(foreign_item.quantity, 1)

    def test_selection_hanya_mengubah_cart_sendiri(self):
        own_cart = Cart.objects.create(user=self.buyer)
        own_item = CartItem.objects.create(
            cart=own_cart,
            product=self.product,
            quantity=1,
        )
        foreign_cart = Cart.objects.create(user=self.other_buyer)
        foreign_item = CartItem.objects.create(
            cart=foreign_cart,
            product=self.product,
            quantity=1,
        )
        self.client.force_login(self.buyer)

        response = self.client.patch(
            reverse("checkout_api:selection"),
            {"selected_ids": [own_item.pk, foreign_item.pk]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        own_item.refresh_from_db()
        foreign_item.refresh_from_db()
        self.assertTrue(own_item.is_selected)
        self.assertFalse(foreign_item.is_selected)

    def test_delete_item_sendiri(self):
        cart = Cart.objects.create(user=self.buyer)
        item = CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=2,
        )
        self.client.force_login(self.buyer)

        response = self.client.delete(
            reverse("checkout_api:item-detail", args=[item.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_id"], item.pk)
        self.assertEqual(response.json()["cart_count"], 0)
        self.assertFalse(CartItem.objects.filter(pk=item.pk).exists())


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class CheckoutCreateAPITest(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username="checkout-api-buyer",
            email="checkout-api-buyer@example.com",
            password="password",
            role="buyer",
            full_name="Budi Lestari",
            phone="08123456789",
            address="Jalan Hijau 10",
        )
        self.seller_one = self._create_seller("checkout-seller-one", "Toko Satu")
        self.seller_two = self._create_seller("checkout-seller-two", "Toko Dua")
        self.product_one = self._create_product(
            self.seller_one,
            "Produk Satu",
            price=10000,
            stock=5,
        )
        self.product_two = self._create_product(
            self.seller_two,
            "Produk Dua",
            price=20000,
            stock=4,
        )
        self.cart = Cart.objects.create(user=self.buyer)
        self.item_one = CartItem.objects.create(
            cart=self.cart,
            product=self.product_one,
            quantity=2,
            is_selected=True,
        )
        self.item_two = CartItem.objects.create(
            cart=self.cart,
            product=self.product_two,
            quantity=1,
            is_selected=True,
        )
        self.summary_url = reverse("checkout_api:summary")
        self.create_url = reverse("checkout_api:orders")
        self.valid_payload = {
            "recipient_name": "Budi Lestari",
            "phone": "08123456789",
            "shipping_address": "Jalan Hijau 10",
            "shipping_method": "reguler",
            "payment_method": "cod",
        }
        self.client.force_login(self.buyer)

    def _create_seller(self, username, store_name):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
            role="seller",
        )
        return SellerProfile.objects.create(user=user, store_name=store_name)

    def _create_product(self, seller, name, price, stock):
        return Product.objects.create(
            seller=seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=price,
            discount=10,
            stock=stock,
            status="verified",
        )

    def test_summary_menghitung_total_per_toko(self):
        response = self.client.get(self.summary_url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["recipient_defaults"]["recipient_name"], "Budi Lestari")
        self.assertEqual(data["items_total"], 36000)
        self.assertEqual(data["item_count"], 3)
        self.assertEqual(data["store_count"], 2)
        self.assertEqual(data["shipping_cost"], 14000)
        self.assertEqual(data["grand_total"], 50000)
        self.assertEqual(len(data["items"]), 2)

    def test_summary_menolak_metode_pengiriman_tidak_valid(self):
        response = self.client.get(
            self.summary_url,
            {"shipping_method": "teleportasi"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("shipping_method", response.json())

    def test_checkout_membuat_satu_order_per_toko(self):
        unselected = CartItem.objects.create(
            cart=self.cart,
            product=self._create_product(
                self.seller_one,
                "Produk Tidak Dipilih",
                price=5000,
                stock=2,
            ),
            quantity=1,
            is_selected=False,
        )

        response = self.client.post(
            self.create_url,
            self.valid_payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(Order.objects.filter(buyer=self.buyer).count(), 2)
        self.assertEqual(OrderItem.objects.count(), 2)
        self.product_one.refresh_from_db()
        self.product_two.refresh_from_db()
        self.assertEqual(self.product_one.stock, 3)
        self.assertEqual(self.product_two.stock, 3)
        self.assertTrue(CartItem.objects.filter(pk=unselected.pk).exists())
        self.assertFalse(CartItem.objects.filter(pk=self.item_one.pk).exists())
        self.assertFalse(CartItem.objects.filter(pk=self.item_two.pk).exists())

        totals = sorted(order["total_price"] for order in response.json()["orders"])
        self.assertEqual(totals, [25000, 25000])

    def test_payload_checkout_wajib_lengkap(self):
        response = self.client.post(
            self.create_url,
            {"recipient_name": "Budi"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("shipping_address", response.json())
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_tanpa_item_terpilih_ditolak(self):
        self.cart.items.update(is_selected=False)

        response = self.client.post(
            self.create_url,
            self.valid_payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_stok_tidak_cukup_membatalkan_seluruh_checkout(self):
        self.product_two.stock = 0
        self.product_two.save(update_fields=["stock"])

        response = self.client.post(
            self.create_url,
            self.valid_payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)
        self.product_one.refresh_from_db()
        self.assertEqual(self.product_one.stock, 5)
        self.assertTrue(CartItem.objects.filter(pk=self.item_one.pk).exists())

    def test_produk_nonverified_membatalkan_seluruh_checkout(self):
        self.product_two.status = "expired"
        self.product_two.save(update_fields=["status"])

        response = self.client.post(
            self.create_url,
            self.valid_payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("tidak tersedia", response.json()["detail"])
        self.assertEqual(Order.objects.count(), 0)


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class OrderHistoryAPITest(TestCase):
    def setUp(self):
        self.buyer = self._create_user("history-buyer", "buyer")
        self.other_buyer = self._create_user("history-other-buyer", "buyer")
        self.seller_user = self._create_user("history-seller", "seller")
        self.other_seller_user = self._create_user(
            "history-other-seller",
            "seller",
        )
        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            store_name="Toko Riwayat",
        )
        self.other_seller = SellerProfile.objects.create(
            user=self.other_seller_user,
            store_name="Toko Lain",
        )
        self.product = self._create_product(self.seller, "Produk Riwayat")
        self.other_product = self._create_product(
            self.other_seller,
            "Produk Lain",
        )
        self.order = self._create_order(
            self.buyer,
            self.seller,
            self.product,
            status="diproses",
        )
        self.other_buyer_order = self._create_order(
            self.other_buyer,
            self.seller,
            self.product,
            status="dikirim",
        )
        self.other_seller_order = self._create_order(
            self.buyer,
            self.other_seller,
            self.other_product,
            status="selesai",
        )
        self.list_url = reverse("checkout_api:orders")

    def _create_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
            role=role,
        )

    def _create_product(self, seller, name):
        return Product.objects.create(
            seller=seller,
            name=name,
            description=f"Deskripsi {name}",
            category="daily_supplies",
            materials="Bambu",
            origin="Bandung",
            price=10000,
            stock=5,
            status="verified",
        )

    def _create_order(self, buyer, seller, product, status):
        order = Order.objects.create(
            buyer=buyer,
            seller=seller,
            store_name=seller.store_name,
            recipient_name=buyer.username,
            phone="08123456789",
            shipping_address="Jalan Lestari",
            shipping_method="reguler",
            payment_method="cod",
            shipping_cost=5000,
            total_price=25000,
            status=status,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            price=10000,
            quantity=2,
        )
        return order

    def test_daftar_pesanan_hanya_dapat_diakses_buyer_atau_seller(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 403)

    def test_buyer_hanya_melihat_pesanan_sendiri_dan_dapat_filter_status(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.list_url, {"status": "diproses"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["orders"][0]["id"], self.order.pk)
        self.assertEqual(data["summary"], {
            "diproses": 1,
            "dikirim": 0,
            "selesai": 1,
        })

    def test_seller_hanya_melihat_pesanan_tokonya(self):
        self.client.force_login(self.seller_user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        order_ids = {order["id"] for order in response.json()["orders"]}
        self.assertEqual(
            order_ids,
            {self.order.pk, self.other_buyer_order.pk},
        )

    def test_detail_pesanan_tidak_bocor_ke_pengguna_lain(self):
        self.client.force_login(self.other_buyer)

        response = self.client.get(
            reverse("checkout_api:order-detail", args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_seller_dapat_mengirim_pesanan_yang_sedang_diproses(self):
        self.client.force_login(self.seller_user)

        response = self.client.patch(
            reverse("checkout_api:order-detail", args=[self.order.pk]),
            {"action": "ship"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "dikirim")

    def test_buyer_dapat_menyelesaikan_pesanan_yang_dikirim(self):
        self.order.status = "dikirim"
        self.order.save(update_fields=["status"])
        self.client.force_login(self.buyer)

        response = self.client.patch(
            reverse("checkout_api:order-detail", args=[self.order.pk]),
            {"action": "complete"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "selesai")

    def test_transisi_status_yang_tidak_sesuai_peran_ditolak(self):
        self.client.force_login(self.buyer)

        response = self.client.patch(
            reverse("checkout_api:order-detail", args=[self.order.pk]),
            {"action": "ship"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "diproses")

    def test_snapshot_pesanan_tetap_terlihat_setelah_produk_dihapus(self):
        self.product.delete()
        self.client.force_login(self.seller_user)

        response = self.client.get(
            reverse("checkout_api:order-detail", args=[self.order.pk])
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["order"]["items"][0]
        self.assertIsNone(item["product_id"])
        self.assertEqual(item["product_name"], "Produk Riwayat")

    def test_pesanan_lama_lintas_toko_tidak_dapat_diubah_bersama(self):
        mixed_order = Order.objects.create(
            buyer=self.buyer,
            seller=None,
            store_name="Pesanan Lama",
            recipient_name=self.buyer.username,
            phone="08123456789",
            shipping_address="Jalan Lestari",
            total_price=20000,
            status="diproses",
        )
        for product in (self.product, self.other_product):
            OrderItem.objects.create(
                order=mixed_order,
                product=product,
                product_name=product.name,
                price=10000,
                quantity=1,
            )
        self.client.force_login(self.seller_user)

        response = self.client.patch(
            reverse("checkout_api:order-detail", args=[mixed_order.pk]),
            {"action": "ship"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
