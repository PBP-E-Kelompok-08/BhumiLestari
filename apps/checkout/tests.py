# AI Assistance Disclosure:
# Unit tests di file ini dibuat dengan bantuan Claude (Anthropic).

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.products.models import Product
from apps.reviews.integrations import pernah_membeli
from apps.users.models import SellerProfile, User

from .models import Cart, CartItem, Order, OrderItem
from .views import _create_order

PASSWORD = "pass12345"


class MultiSellerCheckoutTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.buyer = User.objects.create_user("buyer_checkout", email="buyer_checkout@test.com", password="pw12345!", role="buyer")
        self.sellers = []
        self.products = []
        for n in (1, 2):
            user = User.objects.create_user(f"seller_checkout_{n}", email=f"seller_checkout_{n}@test.com", password="pw12345!", role="seller")
            seller = SellerProfile.objects.create(user=user, store_name=f"Toko {n}")
            product = Product.objects.create(
                seller=seller, name=f"Produk {n}", description="Produk uji",
                category="daily_supplies", materials="bambu", origin="Bandung",
                price=10000, stock=5, status="verified",
                image=SimpleUploadedFile(f"produk{n}.png", b"image"),
                verification_document=SimpleUploadedFile(f"dokumen{n}.pdf", b"document"),
            )
            self.sellers.append(user)
            self.products.append(product)
        cart = Cart.objects.create(user=self.buyer)
        for product in self.products:
            CartItem.objects.create(cart=cart, product=product, quantity=1, is_selected=True)

    def test_checkout_dan_status_terpisah_per_toko(self):
        orders = _create_order(self.buyer, "Pembeli", "08123456789", "Bandung", "reguler", "cod")
        self.assertEqual(len(orders), 2)
        self.assertEqual(Order.objects.filter(buyer=self.buyer).count(), 2)
        self.assertEqual({o.seller_id for o in orders}, {p.seller_id for p in self.products})
        self.assertTrue(all(o.items.count() == 1 and o.total_price == 17000 for o in orders))
        first = Order.objects.get(seller=self.products[0].seller)
        second = Order.objects.get(seller=self.products[1].seller)

        self.client.force_login(self.sellers[0])
        self.client.post(reverse("checkout:order_detail", args=[first.pk]), {"aksi": "terima"})
        self.client.force_login(self.buyer)
        self.client.post(reverse("checkout:order_detail", args=[first.pk]), {"aksi": "selesai"})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, "selesai")
        self.assertEqual(second.status, "diproses")
        self.assertTrue(pernah_membeli(self.buyer, self.products[0].pk))
        self.assertFalse(pernah_membeli(self.buyer, self.products[1].pk))

    def test_pesanan_lama_campuran_tidak_bisa_diselesaikan_bersama(self):
        legacy = Order.objects.create(
            buyer=self.buyer, recipient_name="Pembeli", phone="08123456789",
            shipping_address="Bandung", status="dikirim",
        )
        for product in self.products:
            OrderItem.objects.create(order=legacy, product=product, product_name=product.name, price=10000, quantity=1)
        self.client.force_login(self.buyer)
        self.client.post(reverse("checkout:order_detail", args=[legacy.pk]), {"aksi": "selesai"})
        legacy.refresh_from_db()
        self.assertEqual(legacy.status, "dikirim")


# AI Assistance Disclosure:
# Bagian di bawah ini (helper, CartTests, CheckoutTests, OrderTests, dan seterusnya)
# dibuat dengan bantuan Claude (Anthropic).
# ---------- helper ----------

def make_user(username, role="buyer"):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
        role=role,
    )


def make_seller(username="seller", store_name="Toko Uji"):
    user = make_user(username, role="seller")
    # TODO: tambahkan field wajib lain di SellerProfile kalau ada
    profile = SellerProfile.objects.create(user=user, store_name=store_name)
    return user, profile


def make_product(seller, name="Sedotan Bambu", price=20000, discount=10,
                 stock=10, status="verified"):
    return Product.objects.create(
        seller=seller,
        name=name,
        description="Deskripsi",
        category="daily_supplies",
        materials="Bambu",
        origin="Indonesia",
        price=price,
        discount=discount,
        stock=stock,
        status=status,
    )


def post_json(client, url, data):
    return client.post(url, data=json.dumps(data), content_type="application/json")


class BaseCase(TestCase):
    def login_as(self, username):
        self.client.force_login(User.objects.get(username=username))

    def setUp(self):
        self.buyer = make_user("buyer")
        self.seller_user, self.seller = make_seller()
        self.product = make_product(self.seller)  # final_price = 18000
        self.login_as("buyer")

    def add_item(self, product=None, quantity=1, selected=True):
        cart, _ = Cart.objects.get_or_create(user=self.buyer)
        return CartItem.objects.create(
            cart=cart, product=product or self.product,
            quantity=quantity, is_selected=selected,
        )


# ---------- halaman keranjang ----------

class ShowCartTests(BaseCase):
    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("checkout:show_cart"))
        self.assertEqual(response.status_code, 302)

    def test_empty_cart(self):
        response = self.client.get(reverse("checkout:show_cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keranjang kamu masih kosong")
        self.assertEqual(response.context["total"], 0)

    def test_total_only_counts_selected_items(self):
        other = make_product(self.seller, name="Tas Kanvas", price=35000, discount=0)
        self.add_item(self.product, quantity=2, selected=True)   # 2 x 18000
        self.add_item(other, quantity=1, selected=False)
        response = self.client.get(reverse("checkout:show_cart"))
        self.assertEqual(response.context["total"], 36000)
        self.assertEqual(response.context["selected_count"], 2)
        self.assertEqual(response.context["line_count"], 2)

    def test_items_grouped_by_store(self):
        _, other_seller = make_seller("seller2", "Toko Dua")
        other = make_product(other_seller, name="Produk B")
        self.add_item(self.product)
        self.add_item(other)
        response = self.client.get(reverse("checkout:show_cart"))
        self.assertEqual(len(response.context["stores"]), 2)


# ---------- tambah ke keranjang ----------

class AddToCartTests(BaseCase):
    def url(self, product=None):
        return reverse("checkout:add_to_cart", args=[(product or self.product).pk])

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_anonymous_gets_401(self):
        self.client.logout()
        self.assertEqual(self.client.post(self.url()).status_code, 401)

    def test_seller_gets_403(self):
        self.client.logout()
        self.login_as("seller")
        self.assertEqual(self.client.post(self.url()).status_code, 403)

    def test_add_new_item(self):
        response = self.client.post(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart_count"], 1)
        self.assertEqual(CartItem.objects.get().quantity, 1)

    def test_add_same_item_increments_quantity(self):
        self.client.post(self.url())
        response = self.client.post(self.url())
        self.assertEqual(response.json()["cart_count"], 2)
        self.assertEqual(CartItem.objects.count(), 1)

    def test_unverified_product_not_found(self):
        pending = make_product(self.seller, name="Pending", status="pending")
        self.assertEqual(self.client.post(self.url(pending)).status_code, 404)

    def test_stock_limit(self):
        low = make_product(self.seller, name="Stok Tipis", stock=1)
        self.client.post(self.url(low))
        response = self.client.post(self.url(low))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CartItem.objects.get().quantity, 1)


# ---------- ubah jumlah ----------

class UpdateCartItemTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.item = self.add_item(quantity=1)
        self.url = reverse("checkout:update_cart_item", args=[self.item.pk])

    def test_update_quantity(self):
        response = post_json(self.client, self.url, {"quantity": 5})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 5)

    def test_invalid_quantity(self):
        for bad in (0, -1, "3", None, True):
            response = post_json(self.client, self.url, {"quantity": bad})
            self.assertEqual(response.status_code, 400, msg=f"quantity={bad!r}")

    def test_quantity_over_stock(self):
        response = post_json(self.client, self.url, {"quantity": 11})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 1)

    def test_cannot_update_other_users_item(self):
        other = make_user("buyer2")
        cart = Cart.objects.create(user=other)
        foreign = CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        url = reverse("checkout:update_cart_item", args=[foreign.pk])
        self.assertEqual(post_json(self.client, url, {"quantity": 2}).status_code, 404)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(post_json(self.client, self.url, {"quantity": 2}).status_code, 401)


# ---------- pilih & hapus ----------

class SelectDeleteTests(BaseCase):
    def test_select_items(self):
        a = self.add_item(selected=False)
        b = self.add_item(product=make_product(self.seller, name="B"), selected=True)
        post_json(self.client, reverse("checkout:select_cart_items"), {"selected_ids": [a.pk]})
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertTrue(a.is_selected)
        self.assertFalse(b.is_selected)

    def test_select_ignores_non_int_ids(self):
        a = self.add_item(selected=True)
        post_json(self.client, reverse("checkout:select_cart_items"), {"selected_ids": ["x", True]})
        a.refresh_from_db()
        self.assertFalse(a.is_selected)

    def test_delete_items(self):
        a = self.add_item()
        response = post_json(self.client, reverse("checkout:delete_cart_items"), {"ids": [a.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cart_count"], 0)
        self.assertFalse(CartItem.objects.exists())

    def test_delete_without_ids(self):
        response = post_json(self.client, reverse("checkout:delete_cart_items"), {"ids": []})
        self.assertEqual(response.status_code, 400)

    def test_cannot_delete_other_users_item(self):
        other = make_user("buyer2")
        foreign = CartItem.objects.create(
            cart=Cart.objects.create(user=other), product=self.product, quantity=1
        )
        post_json(self.client, reverse("checkout:delete_cart_items"), {"ids": [foreign.pk]})
        self.assertTrue(CartItem.objects.filter(pk=foreign.pk).exists())


# ---------- checkout ----------

class CheckoutTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("checkout:show_checkout")
        self.valid = {
            "recipient_name": "Budi",
            "phone": "081234567890",
            "address": "Jl. Mangga Besar No. 88",
            "shipping_method": "reguler",   # ongkir 7000
            "payment_method": "cod",
        }

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_seller_redirected(self):
        self.client.logout()
        self.login_as("seller")
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_redirects_to_cart_when_nothing_selected(self):
        self.add_item(selected=False)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("checkout:show_cart"))

    def test_page_loads_with_totals(self):
        self.add_item(quantity=2)  # 36000
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["items_total"], 36000)
        self.assertEqual(response.context["item_count"], 2)
        self.assertEqual(response.context["grand_total"], 36000 + 7000)

    def test_missing_address_rejected(self):
        self.add_item()
        data = {**self.valid, "address": ""}
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("alamat", response.context["error"].lower())
        self.assertEqual(Order.objects.count(), 0)

    def test_invalid_shipping_or_payment_rejected(self):
        self.add_item()
        for field in ("shipping_method", "payment_method"):
            response = self.client.post(self.url, {**self.valid, field: "ngawur"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["error"])
        self.assertEqual(Order.objects.count(), 0)

    def test_successful_checkout(self):
        self.add_item(quantity=2)
        response = self.client.post(self.url, self.valid)
        self.assertRedirects(response, reverse("checkout:order_list"))

        order = Order.objects.get()
        self.assertEqual(order.buyer, self.buyer)
        self.assertEqual(order.shipping_cost, 7000)
        self.assertEqual(order.total_price, 2 * 18000 + 7000)

        oi = OrderItem.objects.get()
        self.assertEqual(oi.product_name, "Sedotan Bambu")
        self.assertEqual(oi.price, 18000)
        self.assertEqual(oi.quantity, 2)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        self.assertFalse(CartItem.objects.exists())

    def test_only_selected_items_are_ordered(self):
        other = make_product(self.seller, name="Tas Kanvas", price=35000, discount=0)
        self.add_item(self.product, quantity=1, selected=True)
        keep = self.add_item(other, quantity=1, selected=False)
        self.client.post(self.url, self.valid)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertTrue(CartItem.objects.filter(pk=keep.pk).exists())

    def test_insufficient_stock_rolls_back(self):
        self.add_item(quantity=3)
        self.product.stock = 2
        self.product.save()
        response = self.client.post(self.url, self.valid)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Stok", response.context["error"])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(CartItem.objects.count(), 1)

    def test_unverified_product_blocks_checkout(self):
        self.add_item()
        self.product.status = "expired"
        self.product.save()
        response = self.client.post(self.url, self.valid)
        self.assertIn("tidak tersedia", response.context["error"])
        self.assertEqual(Order.objects.count(), 0)


# ---------- pesanan ----------

class OrderTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.add_item(quantity=1)
        self.client.post(reverse("checkout:show_checkout"), {
            "recipient_name": "Budi",
            "phone": "081234567890",
            "address": "Jl. Mangga Besar No. 88",
            "shipping_method": "reguler",
            "payment_method": "cod",
        })
        self.order = Order.objects.get()

    def test_buyer_sees_own_order(self):
        response = self.client.get(reverse("checkout:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 1)

    def test_other_buyer_cannot_see_order(self):
        make_user("buyer2")
        self.client.logout()
        self.login_as("buyer2")
        self.assertEqual(len(self.client.get(reverse("checkout:order_list")).context["rows"]), 0)
        url = reverse("checkout:order_detail", args=[self.order.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_seller_sees_order_with_their_products(self):
        self.client.logout()
        self.login_as("seller")
        response = self.client.get(reverse("checkout:order_list"))
        self.assertEqual(len(response.context["rows"]), 1)

    def test_seller_accepts_order(self):
        self.client.logout()
        self.login_as("seller")
        url = reverse("checkout:order_detail", args=[self.order.pk])
        self.client.post(url, {"aksi": "terima"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "dikirim")

    def test_buyer_cannot_finish_before_shipped(self):
        url = reverse("checkout:order_detail", args=[self.order.pk])
        self.client.post(url, {"aksi": "selesai"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "diproses")

    def test_buyer_finishes_shipped_order(self):
        self.order.status = "dikirim"
        self.order.save()
        url = reverse("checkout:order_detail", args=[self.order.pk])
        self.client.post(url, {"aksi": "selesai"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "selesai")
