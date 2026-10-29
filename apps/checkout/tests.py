from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.products.models import Product
from apps.reviews.integrations import pernah_membeli
from apps.users.models import SellerProfile
from .models import Cart, CartItem, Order, OrderItem
from .views import _create_order


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
