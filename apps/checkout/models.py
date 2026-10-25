from django.conf import settings
from django.db import models


class Cart(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Keranjang {self.user}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    is_selected = models.BooleanField(default=False)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cart", "product")
        ordering = ["-added_at"]


class Order(models.Model):
    SHIPPING_CHOICES = [
        ("reguler", "Reguler"), ("kargo", "Kargo"),
        ("express", "Express"), ("same_day", "Same Day"),
    ]
    PAYMENT_CHOICES = [
        ("ewallet", "E-Wallet"), ("qris", "QRIS"),
        ("transfer", "Transfer Bank"), ("cod", "Cash On Delivery"),
    ]
    STATUS_CHOICES = [("diproses", "Diproses"), ("dikirim", "Dikirim"), ("selesai", "Selesai")]

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    recipient_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    shipping_address = models.TextField()
    shipping_method = models.CharField(max_length=20, choices=SHIPPING_CHOICES, default="reguler")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default="cod")
    shipping_cost = models.PositiveIntegerField(default=0)
    total_price = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="diproses")
    created_at = models.DateTimeField(auto_now_add=True)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("products.Product", on_delete=models.SET_NULL, null=True)
    product_name = models.CharField(max_length=150)  # salinan nama saat dibeli
    price = models.PositiveIntegerField()            # salinan harga akhir saat dibeli
    quantity = models.PositiveIntegerField()