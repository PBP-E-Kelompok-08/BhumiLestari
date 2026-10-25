import uuid
from django.core.validators import MaxValueValidator
from django.db import models

class EcoFeature(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    CATEGORY_CHOICES = [
        ("clothing", "Pakaian"),
        ("daily_supplies", "Perlengkapan Sehari-hari"),
        ("home_kitchen", "Home & Kitchen"),
        ("furniture", "Furniture"),
        ("beauty_care", "Beauty & Care"),
    ]

    STATUS_CHOICES = [
        ("pending", "Menunggu verifikasi"),
        ("verified", "Terverifikasi"),
        ("rejected", "Ditolak"),
        ("expired", "Kedaluwarsa"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_product_id = models.CharField(max_length=20, null=True, blank=True, editable=False)
    seller = models.ForeignKey("users.SellerProfile", on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=500)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    materials = models.CharField(max_length=200)
    origin = models.CharField(max_length=120)
    eco_features = models.ManyToManyField(EcoFeature, related_name="products")
    price = models.DecimalField(max_digits=12, decimal_places=0)
    discount = models.PositiveIntegerField(default=0, validators=[MaxValueValidator(100)])
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/images/")
    verification_document = models.FileField(upload_to="products/certifications/")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending", editable=False)
    verification_summary = models.TextField(blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    @property
    def final_price(self):
        return round(self.price * (100 - self.discount) / 100)

    def __str__(self):
        return self.name