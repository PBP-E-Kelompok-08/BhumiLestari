from django.db import models

# Create your models here.

class Product(models.Model):
    STATUS_CHOICES = [
        ("pending", "Menunggu verifikasi"),
        ("approved", "Terverifikasi"),
        ("rejected", "Ditolak"),
    ]

    seller = models.ForeignKey("users.SellerProfile", on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=0)
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/images/")
    certification = models.FileField(upload_to="products/certifications/")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")

    def __str__(self):
        return self.name