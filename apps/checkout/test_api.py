from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.products.models import Product
from apps.users.models import SellerProfile

from .models import Cart, CartItem


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
