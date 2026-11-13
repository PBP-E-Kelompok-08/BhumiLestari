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
        self.create_url = reverse("checkout_api:order-create")
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
