import uuid
from datetime import time
from django.db import models
from django.conf import settings


class ProductKnowledge(models.Model):
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_knowledges"
    )
    product_id = models.CharField(max_length=100, db_index=True, blank=True, null=True)
    product_name = models.CharField(max_length=255, blank=True)
    question = models.CharField(max_length=255, help_text="Kata kunci atau pertanyaan terkait produk / toko")
    answer = models.TextField(help_text="Jawaban resmi yang disetujui penjual")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = self.product_name or self.product_id or "Umum Toko"
        return f"[{target}] {self.question}"


class ChatSession(models.Model):
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

    is_archived_by_buyer = models.BooleanField(default=False)
    is_archived_by_seller = models.BooleanField(default=False)

    # Referensi ke sesi AI awal bila kalo ini merupakan hasil eskalasi/pengalihan
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
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        prefix = "[AI Hist]" if self.is_inherited_from_ai else f"[{self.sender_type}]"
        return f"{prefix} {self.content[:35]}..."


class SellerChatSettings(models.Model):
    """
    Pengaturan Bot Penjual:
    - Bot Auto Reply Toggle
    - Beri Nama Botmu
    - Isi Pesan Sambutan
    - Jam Operasional Toko (Start - End)
    - Pesan Saat Toko Tutup
    """
    seller = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_settings"
    )
    is_auto_reply_enabled = models.BooleanField(default=True)
    bot_name = models.CharField(max_length=100, default="BhumiBot")
    welcome_message = models.TextField(
        blank=True,
        default="Selamat datang di toko kami! Ada yang bisa kami bantu?"
    )
    operating_hours_start = models.TimeField(default=time(8, 0))
    operating_hours_end = models.TimeField(default=time(19, 0))
    closed_message = models.TextField(
        blank=True,
        default="Mohon maaf, toko kami saat ini sedang tutup. Silakan tinggalkan pesan."
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings {self.seller.email} (Bot: {self.bot_name})"


class SessionRating(models.Model):
    session = models.OneToOneField(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="rating"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    rating = models.PositiveSmallIntegerField(help_text="1 sampai 5 bintang")
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Rating {self.rating}★ untuk Sesi {self.session_id}"


class UserReport(models.Model):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_filed"
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reports_received"
    )
    session = models.ForeignKey(
        ChatSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports"
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report dari {self.reporter.email} terhadap {self.reported_user.email}"


class BroadcastChannel(models.Model):
    seller = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broadcast_channel"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    followers_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="archived_broadcast_channels",
        blank=True
    )

    def __str__(self):
        return self.name


class BroadcastMessage(models.Model):
    channel = models.ForeignKey(
        BroadcastChannel,
        on_delete=models.CASCADE,
        related_name="messages"
    )
    content = models.TextField()
    viewed_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.channel.name}] {self.content[:35]}..."
