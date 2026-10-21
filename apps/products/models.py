import uuid
from django.core.validators import MaxValueValidator
from django.db import models

class Product(models.Model):
    STATUS_CHOICES = [
        ("pending", "Menunggu verifikasi"),
        ("approved", "Terverifikasi"),
        ("rejected", "Ditolak"),
    ]

    CATEGORY_CHOICES = [
        ("peralatan_makan", "Peralatan Makan"),
        ("perawatan_diri", "Perawatan Diri"),
        ("rumah_tangga", "Perlengkapan Rumah Tangga"),
        ("fashion", "Fashion"),
        ("lainnya", "Lainnya"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller = models.ForeignKey("users.SellerProfile", on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    price = models.DecimalField(max_digits=12, decimal_places=0)
    discount = models.PositiveIntegerField(default=0, blank=True)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/images/")
    certification = models.FileField(upload_to="products/certifications/")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")

    @property
    def final_price(self):
        return round(self.price * (100 - self.discount) / 100)
    
    def __str__(self):
        return self.name