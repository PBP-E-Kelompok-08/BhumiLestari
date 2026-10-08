import uuid
from django.db import models
from django.conf import settings


class ProductKnowledge(models.Model):
    """
    Daftar pertanyaan dan jawaban resmi yang disetujui penjual per produk.
    AI hanya diperbolehkan menjawab berdasarkan daftar ini.
    """
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_knowledges"
    )
    product_id = models.CharField(max_length=100, db_index=True)
    product_name = models.CharField(max_length=255, blank=True)
    question = models.CharField(max_length=255, help_text="Pertanyaan atau topik terkait produk")
    answer = models.TextField(help_text="Jawaban resmi yang disetujui penjual")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Product Knowledge"
        verbose_name_plural = "Product Knowledges"

    def __str__(self):
        return f"[{self.product_name or self.product_id}] {self.question}"


class ChatSession(models.Model):
    """
    Sesi percakapan dasar.
    """
    TYPE_AI = 'ai'
    TYPE_DIRECT = 'direct'

    SESSION_TYPE_CHOICES = [
        (TYPE_AI, 'AI Assistant Session'),
        (TYPE_DIRECT, 'Direct Seller Session'),
    ]

    STATUS_ACTIVE = 'active'
    STATUS_RESOLVED = 'resolved'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_RESOLVED, 'Resolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="buyer_sessions"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_sessions"
    )
    session_type = models.CharField(max_length=15, choices=SESSION_TYPE_CHOICES, default=TYPE_AI)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"[{self.session_type.upper()}] {self.buyer.email} -> {self.seller.email} ({self.status})"
