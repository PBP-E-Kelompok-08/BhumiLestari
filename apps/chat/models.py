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

    def __str__(self):
        return f"[{self.product_name or self.product_id}] {self.question}"


class ChatSession(models.Model):
    """
    Sesi percakapan. Dapat bertipe 'ai' (Asisten Bot) atau 'direct' (Obrolan Langsung Penjual).
    Memiliki multi-product context via SessionProductContext.
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

    HANDOVER_NONE = 'none'
    HANDOVER_MANUAL = 'manual_user'
    HANDOVER_UNANSWERED = 'unanswered_by_ai'

    HANDOVER_REASONS = [
        (HANDOVER_NONE, 'None'),
        (HANDOVER_MANUAL, 'Diminta Pembeli'),
        (HANDOVER_UNANSWERED, 'Jawaban Tidak Ada di Daftar Penjual'),
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

    # Referensi ke sesi AI awal bila sesi ini merupakan hasil eskalasi/pengalihan
    origin_session = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="escalated_sessions"
    )
    handover_reason = models.CharField(max_length=30, choices=HANDOVER_REASONS, default=HANDOVER_NONE)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"[{self.session_type.upper()}] {self.buyer.email} -> {self.seller.email} ({self.status})"


class SessionProductContext(models.Model):
    """
    Konteks produk yang dibahas dalam suatu ChatSession.
    Satu sesi bisa memiliki satu atau lebih konteks produk.
    """
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="product_contexts"
    )
    product_id = models.CharField(max_length=100, db_index=True)
    product_name = models.CharField(max_length=255, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'product_id')
        ordering = ['added_at']

    def __str__(self):
        return f"Sesi {self.session_id} - Produk: {self.product_name or self.product_id}"


class ChatMessage(models.Model):
    """
    Riwayat pesan individu dalam sesi percakapan.
    Pesan dari sesi AI yang diwariskan ke sesi direct ditandai dengan is_inherited_from_ai=True.
    """
    SENDER_BUYER = 'buyer'
    SENDER_SELLER = 'seller'
    SENDER_AI = 'ai'
    SENDER_SYSTEM = 'system'

    SENDER_CHOICES = [
        (SENDER_BUYER, 'Buyer'),
        (SENDER_SELLER, 'Seller'),
        (SENDER_AI, 'AI Assistant'),
        (SENDER_SYSTEM, 'System Notification'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    sender_type = models.CharField(max_length=15, choices=SENDER_CHOICES)
    content = models.TextField()
    is_inherited_from_ai = models.BooleanField(
        default=False,
        help_text="True jika pesan ini merupakan riwayat AI dari sesi sebelumnya yang diteruskan ke sesi direct."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        prefix = "[AI Hist]" if self.is_inherited_from_ai else f"[{self.sender_type}]"
        return f"{prefix} {self.content[:35]}..."
