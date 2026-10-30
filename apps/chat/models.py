import uuid
from datetime import time
from django.db import models
from django.conf import settings


class ProductKnowledge(models.Model):
    """
    Model basis pengetahuan (knowledge base) Q&A toko dan produk.
    Digunakan sebagai rujukan jawaban resmi penjual yang akan disuntikkan
    ke dalam system prompt AI Assistant (EucalypBot / BhumiBot).
    """
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
        """Representasi string untuk entri pengetahuan produk/toko."""
        target = self.product_name or self.product_id or "Umum Toko"
        return f"[{target}] {self.question}"


class ChatSession(models.Model):
    """
    Model sesi percakapan antara Pembeli (buyer) dan Penjual (seller).
    Mendukung dua tipe sesi:
    1. 'ai'     : Obrolan pembeli dengan bot AI asisten toko.
    2. 'direct' : Obrolan langsung pembeli dengan penjual manusia.
    Menyimpan relasi origin_session untuk melacak riwayat eskalasi (handover).
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
    HANDOVER_BOT_DISABLED = 'bot_disabled'

    HANDOVER_REASONS = [
        (HANDOVER_NONE, 'None'),
        (HANDOVER_MANUAL, 'Diminta Pembeli'),
        (HANDOVER_UNANSWERED, 'Jawaban Tidak Ada di Daftar Penjual'),
        (HANDOVER_BOT_DISABLED, 'Bot Auto Reply Dinonaktifkan'),
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
        """Representasi string sesi obrolan (tipe sesi, pembeli -> penjual, dan status)."""
        return f"[{self.session_type.upper()}] {self.buyer.email} -> {self.seller.email} ({self.status})"


class SessionProductContext(models.Model):
    """
    Model konteks produk yang sedang dibahas dalam suatu sesi percakapan.
    Ditampilkan sebagai chip produk di bawah header chat dan disuntikkan
    ke dalam konteks prompt AI.
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
        """Representasi string konteks produk untuk sesi terkait."""
        return f"Sesi {self.session_id} - Produk: {self.product_name or self.product_id}"


class ChatMessage(models.Model):
    """
    Model pesan individual di dalam suatu sesi obrolan.
    Mencakup pengirim (buyer, seller, ai, system), penanda dibaca (is_read),
    serta flag is_inherited_from_ai untuk menandai pesan riwayat AI
    yang disalin saat eskalasi ke direct session.
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
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        """Representasi string pesan (potongan teks dan tipe pengirim)."""
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
        """Representasi string untuk pengaturan bot penjual."""
        return f"Settings {self.seller.email} (Bot: {self.bot_name})"


class SessionRating(models.Model):
    """
    Model ulasan & rating bintang (1 sampai 5) untuk sesi percakapan.
    Diisi oleh pembeli melalui popup rating (Screen 7).
    """
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
        """Representasi string rating sesi percakapan."""
        return f"Rating {self.rating}★ untuk Sesi {self.session_id}"


class UserReport(models.Model):
    """
    Model laporan aduan pengguna (moderasi obrolan).
    Dapat diajukan oleh pembeli terhadap penjual (Screen 8)
    maupun oleh penjual terhadap pembeli.
    """
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
        """Representasi string laporan pengguna."""
        return f"Report dari {self.reporter.email} terhadap {self.reported_user.email}"


class BroadcastChannel(models.Model):
    """
    Model saluran siaran toko (Broadcast Channel).
    Tiap penjual memiliki tepat satu channel resmi untuk menyiarkan
    pengumuman produk, diskon, atau info toko kepada para pengikut.
    """
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
    followers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="followed_broadcast_channels",
        blank=True
    )
    added_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="added_broadcast_channels",
        blank=True
    )

    def __str__(self):
        """Representasi string nama saluran siaran."""
        return self.name


class BroadcastMessage(models.Model):
    """
    Model pesan siaran individual yang dikirim oleh pemilik toko
    ke dalam BroadcastChannel miliknya.
    """
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
        """Representasi string pesan siaran."""
        return f"[{self.channel.name}] {self.content[:35]}..."


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_broadcast_channel_for_seller_user(sender, instance, created, **kwargs):
    """
    Signal receiver Django (post_save pada User).
    Menjamin bahwa setiap pengguna dengan role='seller' otomatis
    memiliki tepat 1 saluran siaran resmi (BroadcastChannel).
    """
    if getattr(instance, "role", "") == "seller":
        store_name = instance.full_name or (instance.email.split("@")[0] if instance.email else "Toko Penjual")
        if hasattr(instance, "seller_profile") and instance.seller_profile:
            store_name = instance.seller_profile.store_name
        BroadcastChannel.objects.get_or_create(
            seller=instance,
            defaults={
                "name": store_name,
                "description": f"Saluran pengumuman resmi {store_name}",
                "followers_count": 0,
            }
        )

