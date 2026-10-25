import random
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta

# Custom User Model
class User(AbstractUser):
    ROLE_BUYER = 'buyer'
    ROLE_SELLER = 'seller'
    CHOICE_ROLE = [
        (ROLE_BUYER, 'buyer'),
        (ROLE_SELLER, 'seller'),
    ]

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=10, choices=CHOICE_ROLE, default=ROLE_BUYER)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

# Profil tambahan untuk penjual
class SellerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='seller_profile')
    store_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.store_name

    @property
    def external_id(self):
         return f"sel-{self.pk:03d}"

# Model OTP
class OTPToken(models.Model):
    email = models.EmailField()
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_valid(self):
        now = timezone.now()
        return not self.is_used and self.created_at >= now - timedelta(minutes=5)

    @staticmethod
    def generate_otp():
        return str(random.randint(100000, 999999))

class PaymentMethod(models.Model):
    TYPE_CHOICES = [
        ('bank', 'Bank'),
        ('ewallet', 'E-Wallet'),
        ('qris', 'QRIS'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    method_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    provider = models.CharField(max_length=100)          # BCA, Mandiri, GoPay, dst.
    account_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    def masked_number(self):
        return '•••• ' + self.account_number[-4:]
    
    def __str__(self):
        return f"{self.provider} - {self.masked_number()}"