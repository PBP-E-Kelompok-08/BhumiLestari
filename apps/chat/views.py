import json
import logging
from datetime import datetime, time
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Q, F
from django.utils import timezone

from apps.chat.models import (
    ProductKnowledge,
    ChatSession,
    SessionProductContext,
    ChatMessage,
    SellerChatSettings,
    SessionRating,
    UserReport,
    BroadcastChannel,
    BroadcastMessage,
)
from apps.chat.services.ai_service import (
    build_system_prompt,
    query_openrouter,
    parse_handover_signal,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _json_error(message, status=400):
    """
    Helper untuk mengembalikan respons JSON standar ketika terjadi kesalahan (error).

    Args:
        message (str): Pesan kesalahan yang deskriptif dan ramah pengguna.
        status (int, optional): Kode HTTP status response (default: 400 Bad Request).

    Returns:
        JsonResponse: Objek respons JSON berformat {"status": "error", "message": message}.
    """
    return JsonResponse({"status": "error", "message": message}, status=status)


def _get_seller_store_name(seller):
    """
    Mengambil nama toko penjual untuk tampilan antarmuka dan system prompt bot AI.

    Prioritas pengambilan nama:
    1. `seller.seller_profile.store_name` (nama toko resmi jika ada profil seller).
    2. `seller.full_name` (nama lengkap user).
    3. Username dari prefix email (fallback jika nama belum diisi).

    Args:
        seller (User): Objek user penjual.

    Returns:
        str: Nama toko atau nama penjual yang siap ditampilkan.
    """
    if hasattr(seller, 'seller_profile') and seller.seller_profile:
        return seller.seller_profile.store_name
    return seller.full_name or seller.email.split('@')[0]


def _get_seller_chat_settings(seller):
    """
    Mengambil atau membuat entri pengaturan obrolan (`SellerChatSettings`) untuk penjual.

    Args:
        seller (User): Objek user penjual.

    Returns:
        SellerChatSettings: Objek pengaturan chat dan bot AI milik penjual tersebut.
    """
    settings_obj, _ = SellerChatSettings.objects.get_or_create(
        seller=seller,
        defaults={
            "bot_name": "EucalypBot" if "eucalyp" in (seller.email or "").lower() else "BhumiBot"
        }
    )
    return settings_obj


def _format_time_str(t):
    """
    Memformat objek waktu (`datetime.time` atau string) menjadi representasi string 'HH:MM'.

    Args:
        t (time|str|None): Objek waktu jam atau string waktu.

    Returns:
        str: Representasi format jam dua digit 'HH:MM' (default '00:00' jika kosong).
    """
    if not t:
        return "00:00"
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")
    return str(t)[:5]


def _is_store_open(chat_settings):
    """
    Memeriksa apakah toko penjual saat ini sedang dalam jam operasional buka.
    Menggunakan zona waktu lokal Jakarta (WIB / Asia/Jakarta).

    Logika:
    - Jika `start <= end`: Toko buka pada rentang hari yang sama (misal 08:00 - 19:00).
    - Jika `start > end`: Toko buka melintasi tengah malam (misal 20:00 - 04:00).

    Args:
        chat_settings (SellerChatSettings): Pengaturan jam operasional bot penjual.

    Returns:
        bool: True jika saat ini toko buka, False jika toko sedang tutup.
    """
    try:
        from zoneinfo import ZoneInfo
        now_time = datetime.now(ZoneInfo("Asia/Jakarta")).time()
    except Exception:
        now_time = datetime.now().time()

    start = chat_settings.operating_hours_start
    end = chat_settings.operating_hours_end

    if isinstance(start, str):
        parts = [int(p) for p in start.split(":")[:2]]
        start = time(parts[0], parts[1])
    if isinstance(end, str):
        parts = [int(p) for p in end.split(":")[:2]]
        end = time(parts[0], parts[1])

    if start <= end:
        return start <= now_time <= end
    return now_time >= start or now_time <= end


def _transfer_to_direct_session(ai_session, reason=ChatSession.HANDOVER_MANUAL, forward_question=None):
    """
    Mengalihkan sesi obrolan AI ke sesi obrolan langsung (direct) dengan penjual (Handover).

    Alur:
    1. Mengambil atau membuat sesi bertipe `TYPE_DIRECT` antara pembeli dan penjual terkait.
    2. Menyalin konteks produk (`SessionProductContext`) dari sesi AI ke sesi direct.
    3. Menyalin seluruh riwayat obrolan AI ke sesi direct (`is_inherited_from_ai=True`)
       agar penjual langsung memahami apa yang ditanyakan pembeli sebelumnya.
    4. Menyisipkan pesan sistem pembatas: '--- Anda kini terhubung langsung dengan penjual... ---'.
    5. Jika terdapat pertanyaan pembeli yang belum terjawab (`forward_question`),
       pesan tersebut otomatis diposting di bawah pembatas sebagai pesan baru yang belum dibaca penjual.
    6. Menandai sesi AI lama sebagai `STATUS_RESOLVED`.

    Args:
        ai_session (ChatSession): Sesi AI awal yang ingin dialihkan.
        reason (str, optional): Alasan pengalihan ('manual' atau 'unanswered').
        forward_question (str, optional): Pertanyaan pembeli yang belum terjawab oleh AI.

    Returns:
        ChatSession: Objek sesi direct aktif yang siap digunakan oleh pembeli dan penjual.
    """
    direct_session = ChatSession.objects.filter(
        buyer=ai_session.buyer,
        seller=ai_session.seller,
        session_type=ChatSession.TYPE_DIRECT,
    ).order_by("-updated_at").first()

    if not direct_session:
        direct_session = ChatSession.objects.create(
            buyer=ai_session.buyer,
            seller=ai_session.seller,
            session_type=ChatSession.TYPE_DIRECT,
            status=ChatSession.STATUS_ACTIVE,
            origin_session=ai_session,
            handover_reason=reason,
        )
    else:
        # Sesi direct yang dipakai ulang harus benar-benar terbuka kembali untuk kedua pihak.
        # Tanpa reset arsip penjual, handover baru bisa tidak terlihat di inbox penjual.
        direct_session.status = ChatSession.STATUS_ACTIVE
        direct_session.is_archived_by_buyer = False
        direct_session.is_archived_by_seller = False
        direct_session.save(
            update_fields=[
                "status",
                "is_archived_by_buyer",
                "is_archived_by_seller",
                "updated_at",
            ]
        )

    for p_ctx in ai_session.product_contexts.all():
        SessionProductContext.objects.get_or_create(
            session=direct_session,
            product_id=p_ctx.product_id,
            defaults={"product_name": p_ctx.product_name}
        )

    # Bila ada forward_question (pertanyaan pembeli yang memicu pengalihan karena tidak terjawab oleh AI),
    # identifikasi ID pesan tersebut di ai_session agar tidak disalin ganda di atas pembatas
    forward_msg_id = None
    if forward_question:
        last_buyer_in_ai = ai_session.messages.filter(
            sender_type=ChatMessage.SENDER_BUYER,
            content=forward_question
        ).order_by("-created_at").first()
        if last_buyer_in_ai:
            forward_msg_id = last_buyer_in_ai.id

    ai_messages = ai_session.messages.order_by("created_at")
    for msg in ai_messages:
        if msg.sender_type == ChatMessage.SENDER_SYSTEM and ("--- Anda kini" in msg.content or "Percakapan telah dialihkan" in msg.content):
            continue
        if forward_msg_id and msg.id == forward_msg_id:
            continue
        if not direct_session.messages.filter(content=msg.content, created_at=msg.created_at).exists():
            new_msg = ChatMessage.objects.create(
                session=direct_session,
                sender=msg.sender,
                sender_type=msg.sender_type,
                content=msg.content,
                is_inherited_from_ai=True,
                is_read=True,
            )
            ChatMessage.objects.filter(id=new_msg.id).update(created_at=msg.created_at)

    store_name = _get_seller_store_name(ai_session.seller)
    ChatMessage.objects.create(
        session=direct_session,
        sender=None,
        sender_type=ChatMessage.SENDER_SYSTEM,
        content=f"--- Anda kini terhubung langsung dengan penjual ({store_name}). Riwayat obrolan dengan AI tersimpan di atas. ---",
        is_inherited_from_ai=False,
        is_read=True,
    )

    if forward_question:
        ChatMessage.objects.create(
            session=direct_session,
            sender=ai_session.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content=forward_question,
            is_inherited_from_ai=False,
            is_read=False,
        )

    ai_session.status = ChatSession.STATUS_RESOLVED
    ai_session.handover_reason = reason
    ai_session.save(update_fields=["status", "handover_reason", "updated_at"])

    ChatMessage.objects.create(
        session=ai_session,
        sender=None,
        sender_type=ChatMessage.SENDER_SYSTEM,
        content="Percakapan telah dialihkan ke ruang obrolan langsung dengan penjual.",
        is_inherited_from_ai=False,
        is_read=True,
    )

    # Pastikan direct_session memiliki timestamp update paling mutakhir
    direct_session.updated_at = timezone.now()
    direct_session.save()

    return direct_session


def _transfer_to_ai_session(direct_session):
    """
    Mengalihkan sesi obrolan langsung (direct) kembali ke sesi asisten AI bot toko.

    Alur:
    1. Mengambil atau membuat sesi bertipe `TYPE_AI` antara pembeli dan penjual terkait.
    2. Menyalin konteks produk (`SessionProductContext`) dari sesi direct ke sesi AI.
    3. Menyalin pesan-pesan obrolan terbaru dari sesi direct ke sesi AI agar bot memiliki konteks penuh.
    4. Menyisipkan pesan sistem: '--- Anda kini beralih kembali ke Asisten AI (<bot_name>)... ---'.
    5. Menandai sesi direct sebelumnya sebagai `STATUS_RESOLVED`.

    Args:
        direct_session (ChatSession): Sesi chat direct yang ingin dialihkan kembali ke AI.

    Returns:
        ChatSession: Objek sesi AI aktif yang siap menerima pertanyaan pembeli berikutnya.
    """
    ai_session = ChatSession.objects.filter(
        buyer=direct_session.buyer,
        seller=direct_session.seller,
        session_type=ChatSession.TYPE_AI
    ).order_by("-updated_at").first()

    if not ai_session:
        ai_session = ChatSession.objects.create(
            buyer=direct_session.buyer,
            seller=direct_session.seller,
            session_type=ChatSession.TYPE_AI,
            status=ChatSession.STATUS_ACTIVE,
            origin_session=direct_session
        )
    else:
        ai_session.status = ChatSession.STATUS_ACTIVE
        ai_session.is_archived_by_buyer = False
        ai_session.save(update_fields=["status", "is_archived_by_buyer", "updated_at"])

    # Salin product contexts dari direct_session bila belum ada
    for p_ctx in direct_session.product_contexts.all():
        SessionProductContext.objects.get_or_create(
            session=ai_session,
            product_id=p_ctx.product_id,
            defaults={"product_name": p_ctx.product_name}
        )

    # Salin pesan-pesan dari direct session yang belum ada di ai_session
    direct_messages = direct_session.messages.order_by("created_at")
    for msg in direct_messages:
        if msg.sender_type == ChatMessage.SENDER_SYSTEM and ("--- Anda kini" in msg.content or "Percakapan telah dialihkan" in msg.content):
            continue
        if not ai_session.messages.filter(content=msg.content, created_at=msg.created_at).exists():
            new_msg = ChatMessage.objects.create(
                session=ai_session,
                sender=msg.sender,
                sender_type=msg.sender_type,
                content=msg.content,
                is_inherited_from_ai=msg.is_inherited_from_ai,
                is_read=True,
            )
            ChatMessage.objects.filter(id=new_msg.id).update(created_at=msg.created_at)

    chat_settings = _get_seller_chat_settings(direct_session.seller)
    bot_name = chat_settings.bot_name if (chat_settings and chat_settings.bot_name) else "Asisten Toko"

    # Notifikasi sistem transisi ke bot AI
    ChatMessage.objects.create(
        session=ai_session,
        sender=None,
        sender_type=ChatMessage.SENDER_SYSTEM,
        content=f"--- Anda kini beralih kembali ke Asisten AI ({bot_name}). Riwayat obrolan dengan penjual tersimpan di atas. ---",
        is_inherited_from_ai=False,
        is_read=True,
    )

    # Tandai direct_session sebagai resolved
    direct_session.status = ChatSession.STATUS_RESOLVED
    direct_session.save(update_fields=["status", "updated_at"])

    ChatMessage.objects.create(
        session=direct_session,
        sender=None,
        sender_type=ChatMessage.SENDER_SYSTEM,
        content=f"Percakapan telah dialihkan kembali ke asisten AI ({bot_name}).",
        is_inherited_from_ai=False,
        is_read=True,
    )

    ai_session.updated_at = timezone.now()
    ai_session.save(update_fields=["updated_at"])

    return ai_session


# ==============================================================================
# BUYER & AI CHAT API
# ==============================================================================

@login_required
def get_or_create_ai_session_api(request):
    """
    Mengambil sesi chat AI yang sudah ada atau membuat sesi obrolan AI baru untuk toko dan produk tertentu.

    Metode: POST
    Endpoint: `/chat/api/sessions/ai/`

    Payload JSON:
    ```json
    {
        "seller_id": 1,
        "products": [
            {"product_id": "1", "product_name": "Sabun Bambu Ramah Lingkungan"},
            {"product_id": "2", "product_name": "Sikat Gigi Bambu"}
        ]
    }
    ```

    Alur:
    1. Validasi user bukan penjual itu sendiri.
    2. Cek apakah ada sesi AI aktif. Jika belum ada tetapi ada sesi direct aktif,
       alihkan sesi direct ke sesi AI (`_transfer_to_ai_session`).
    3. Jika benar-benar baru, buat `ChatSession(type='ai')` dan kirim sambutan selamat datang
       otomatis dari bot jika `is_auto_reply_enabled=True`.
    4. Lampirkan produk ke `SessionProductContext`.

    Args:
        request (HttpRequest): Objek HTTP request Django (wajib login).

    Returns:
        JsonResponse: Detail session_id, tipe sesi, info penjual, dan daftar konteks produk.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    seller_id = data.get("seller_id")
    if not seller_id:
        return _json_error("Parameter seller_id wajib disertakan.")

    seller = get_object_or_404(User, id=seller_id)
    buyer = request.user

    if buyer == seller:
        return _json_error("Penjual tidak dapat membuka sesi tanya produk ke diri sendiri.")

    chat_settings = _get_seller_chat_settings(seller)
    is_new = False

    # 1. Cari apakah sudah ada sesi AI aktif dengan toko ini
    target_session = ChatSession.objects.filter(
        buyer=buyer,
        seller=seller,
        session_type=ChatSession.TYPE_AI,
        status=ChatSession.STATUS_ACTIVE,
    ).first()

    # 2. Jika tidak ada sesi AI aktif, tetapi ada sesi DIRECT aktif, alihkan ke sesi AI
    # sehingga riwayat percakapan dengan penjual tetap tersimpan dan obrolan dimulai dengan AI chatbot
    if not target_session:
        active_direct = ChatSession.objects.filter(
            buyer=buyer,
            seller=seller,
            session_type=ChatSession.TYPE_DIRECT,
            status=ChatSession.STATUS_ACTIVE,
        ).first()

        if active_direct:
            target_session = _transfer_to_ai_session(active_direct)
        else:
            # 3. Buat sesi AI baru
            target_session = ChatSession.objects.create(
                buyer=buyer,
                seller=seller,
                session_type=ChatSession.TYPE_AI,
                status=ChatSession.STATUS_ACTIVE,
            )
            is_new = True

    # Jika sesi baru & auto reply bot aktif, kirim sambutan selamat datang dari bot
    if is_new and chat_settings.is_auto_reply_enabled and chat_settings.welcome_message:
        ChatMessage.objects.create(
            session=target_session,
            sender=None,
            sender_type=ChatMessage.SENDER_AI,
            content=f"{chat_settings.welcome_message}\n\n-{chat_settings.bot_name}",
        )

    products = data.get("products", [])
    for p in products:
        p_id = str(p.get("product_id", "")).strip()
        p_name = str(p.get("product_name", "")).strip()
        if p_id:
            SessionProductContext.objects.get_or_create(
                session=target_session,
                product_id=p_id,
                defaults={"product_name": p_name}
            )

    target_session.is_archived_by_buyer = False
    target_session.updated_at = timezone.now()
    target_session.save(update_fields=["is_archived_by_buyer", "updated_at"])

    contexts = [
        {"product_id": c.product_id, "product_name": c.product_name}
        for c in target_session.product_contexts.all()
    ]

    return JsonResponse({
        "status": "success",
        "session_id": str(target_session.id),
        "session_type": target_session.session_type,
        "seller": {
            "id": seller.id,
            "email": seller.email,
            "store_name": _get_seller_store_name(seller),
            "bot_name": chat_settings.bot_name,
            "is_auto_reply_enabled": chat_settings.is_auto_reply_enabled,
        },
        "product_contexts": contexts,
    })


@login_required
def add_product_context_api(request, session_id):
    """
    Menambahkan konteks produk ke sesi percakapan (POST) atau menghapus konteks produk (DELETE).

    Metode: POST | DELETE
    Endpoint: `/chat/api/sessions/<session_id>/products/`

    Payload POST JSON:
    ```json
    {
        "products": [
            {"product_id": "1", "product_name": "Sabun Bambu"}
        ]
    }
    ```

    DELETE Query / Body:
    `?product_id=<id>` atau `{"product_id": "all"}` untuk menghapus semua konteks produk.

    Args:
        request (HttpRequest): Request pengguna (harus merupakan buyer atau seller dari sesi tersebut).
        session_id (str|UUID): ID percakapan target.

    Returns:
        JsonResponse: Daftar konteks produk terbaru (`all_product_contexts`) dan status operasi.
    """
    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller):
        return _json_error("Akses ditolak.", status=403)

    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return _json_error("Format JSON tidak valid.")

        products = data.get("products", [])
        added = []
        for p in products:
            p_id = str(p.get("product_id", "")).strip()
            p_name = str(p.get("product_name", "")).strip()
            if p_id:
                ctx, created = SessionProductContext.objects.get_or_create(
                    session=session,
                    product_id=p_id,
                    defaults={"product_name": p_name}
                )
                if created:
                    added.append({"product_id": ctx.product_id, "product_name": ctx.product_name})

        all_contexts = [
            {"product_id": c.product_id, "product_name": c.product_name}
            for c in session.product_contexts.all()
        ]

        return JsonResponse({
            "status": "success",
            "added": added,
            "all_product_contexts": all_contexts,
        })

    elif request.method == "DELETE":
        product_id = request.GET.get("product_id")
        if not product_id and request.body:
            try:
                body_data = json.loads(request.body.decode("utf-8"))
                product_id = body_data.get("product_id")
            except Exception:
                pass

        if product_id and product_id != "all":
            deleted_count, _ = session.product_contexts.filter(product_id=product_id).delete()
            message = f"Konteks produk {product_id} berhasil dihapus."
        else:
            deleted_count, _ = session.product_contexts.all().delete()
            message = "Semua konteks produk berhasil dihapus."

        all_contexts = [
            {"product_id": c.product_id, "product_name": c.product_name}
            for c in session.product_contexts.all()
        ]

        return JsonResponse({
            "status": "success",
            "message": message,
            "deleted_count": deleted_count,
            "all_product_contexts": all_contexts,
        })

    return _json_error("Hanya metode POST dan DELETE yang diizinkan.", status=405)


@login_required
def delete_product_context_api(request, session_id):
    """
    Endpoint alternatif untuk menghapus satu atau seluruh konteks produk dari percakapan.

    Metode: POST | DELETE
    Endpoint: `/chat/api/sessions/<session_id>/products/delete/`

    Parameter:
    - Query string `?product_id=1` atau JSON body `{"product_id": "1"}`: Hapus 1 produk spesifik.
    - `product_id="all"` atau tanpa parameter: Hapus semua konteks produk dari sesi ini.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan target.

    Returns:
        JsonResponse: Konfirmasi penghapusan dan daftar konteks produk tersisa.
    """
    if request.method not in ("POST", "DELETE"):
        return _json_error("Hanya metode POST atau DELETE yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller):
        return _json_error("Akses ditolak.", status=403)

    product_id = request.GET.get("product_id")
    if not product_id and request.body:
        try:
            body_data = json.loads(request.body.decode("utf-8"))
            product_id = body_data.get("product_id")
        except Exception:
            pass

    if product_id and product_id != "all":
        deleted_count, _ = session.product_contexts.filter(product_id=product_id).delete()
        message = f"Konteks produk {product_id} berhasil dihapus."
    else:
        deleted_count, _ = session.product_contexts.all().delete()
        message = "Semua konteks produk berhasil dihapus."

    all_contexts = [
        {"product_id": c.product_id, "product_name": c.product_name}
        for c in session.product_contexts.all()
    ]

    return JsonResponse({
        "status": "success",
        "message": message,
        "deleted_count": deleted_count,
        "all_product_contexts": all_contexts,
    })


@login_required
def search_sellers_api(request):
    """
    Mencari toko penjual dengan pencarian teks (AJAX debounce) atau menyajikan rekomendasi toko acak bila query kosong.

    Metode: GET
    Endpoint: `/chat/api/sellers/search/?q=<query>`

    Alur:
    1. Filter pengguna yang memiliki peran `seller` atau profil seller, kecuali diri sendiri.
    2. Jika terdapat parameter `q`, cari berdasarkan nama toko, nama penjual, username, atau email (limit 15).
    3. Jika `q` kosong, ambil 10 toko acak (`order_by('?')`) sebagai rekomendasi cepat bagi pembeli.
    4. Hitung inisial huruf untuk avatar antarmuka.

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        JsonResponse: Daftar penjual berformat `{"status": "success", "sellers": [...]}`.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    q = request.GET.get("q", "").strip()

    sellers_qs = User.objects.filter(
        Q(role="seller") | Q(seller_profile__isnull=False)
    ).distinct().exclude(id=request.user.id)

    if q:
        sellers_qs = sellers_qs.filter(
            Q(seller_profile__store_name__icontains=q) |
            Q(full_name__icontains=q) |
            Q(email__icontains=q) |
            Q(username__icontains=q)
        ).distinct()[:15]
    else:
        # Jika query kosong, tampilkan toko random
        sellers_qs = sellers_qs.order_by("?")[:10]

    results = []
    for s in sellers_qs:
        store_name = _get_seller_store_name(s)
        words = store_name.split()
        if len(words) > 1 and words[0].lower() == "toko":
            initial = words[1][0].upper()
        elif store_name:
            initial = store_name[0].upper()
        else:
            initial = "T"

        results.append({
            "id": s.id,
            "store_name": store_name,
            "email": s.email,
            "initial": initial,
        })

    return JsonResponse({
        "status": "success",
        "total": len(results),
        "sellers": results,
    })


@login_required
def send_ai_message_api(request, session_id):
    """
    Mengirimkan pertanyaan pembeli ke asisten AI bot toko dan memproses balasannya.

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/ai-send/`

    Payload JSON:
    ```json
    {"content": "Berapa lama daya tahan sabun bambu ini?"}
    ```

    Alur:
    1. Validasi sesi bertipe `TYPE_AI` dan pengirim adalah pembeli sesi ini.
    2. Simpan pesan pembeli ke database (`ChatMessage`).
    3. Cek jam operasional toko (`_is_store_open`):
       Jika toko tutup dan auto reply aktif, balas dengan `closed_message`.
    4. Ambil basis pengetahuan Q&A (`ProductKnowledge`) dan katalog produk aktif penjual (`Product`).
    5. Susun system prompt (`build_system_prompt`) serta riwayat percakapan terakhir (sliding window 8 pesan).
    6. Hubungi API OpenRouter (`query_openrouter`).
       - Jika API error/gagal: lakukan fallback otomatis handover ke penjual (`_transfer_to_direct_session`).
    7. Analisis balasan AI (`parse_handover_signal`):
       - Jika terdeteksi tag `[HANDOVER_SELLER]`: alihkan sesi ke penjual dan teruskan pertanyaan pembeli.
       - Jika jawaban valid: simpan pesan AI ke database dan kembalikan ke frontend pembeli.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan AI target.

    Returns:
        JsonResponse: Objek respons JSON berisi teks balasan AI atau status handover.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli di sesi ini yang dapat mengirim pesan ke AI.", status=403)

    if session.session_type != ChatSession.TYPE_AI:
        return _json_error("Sesi ini bukan sesi AI. Gunakan endpoint direct-send.", status=400)

    if session.status != ChatSession.STATUS_ACTIVE:
        return _json_error("Sesi AI ini sudah selesai dan tidak dapat menerima pesan baru.", status=400)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    content = str(data.get("content", "")).strip()
    if not content:
        return _json_error("Pesan content tidak boleh kosong.")

    user_msg = ChatMessage.objects.create(
        session=session,
        sender=request.user,
        sender_type=ChatMessage.SENDER_BUYER,
        content=content,
        is_read=True,
    )

    chat_settings = _get_seller_chat_settings(session.seller)
    store_name = _get_seller_store_name(session.seller)
    bot_name = chat_settings.bot_name

    if chat_settings.is_auto_reply_enabled and not _is_store_open(chat_settings):
        closed_reply = f"{chat_settings.closed_message}\n\n-{bot_name}"
        ai_msg = ChatMessage.objects.create(
            session=session,
            sender=None,
            sender_type=ChatMessage.SENDER_AI,
            content=closed_reply,
        )
        return JsonResponse({
            "status": "success",
            "handover": False,
            "reply": closed_reply,
            "is_closed": True,
            "message_id": str(ai_msg.id),
            "session_id": str(session.id),
        })

    product_contexts = list(session.product_contexts.all())

    # Ambil seluruh Q&A produk aktif dari penjual ini agar AI dapat menjawab seputar katalog toko
    all_product_qas = ProductKnowledge.objects.filter(
        seller=session.seller,
        is_active=True
    ).exclude(product_id__isnull=True).exclude(product_id="")

    knowledges_by_product = {}
    for k in all_product_qas:
        knowledges_by_product.setdefault(k.product_id, []).append(k)

    general_knowledges = list(ProductKnowledge.objects.filter(
        Q(product_id__isnull=True) | Q(product_id=""),
        seller=session.seller,
        is_active=True
    ))

    real_products = []
    try:
        from apps.products.models import Product
        real_products = list(
            Product.objects.filter(seller__user=session.seller)
            .exclude(status__in=["rejected", "expired"])[:15]
        )
    except Exception as e:
        logger.warning(f"Gagal mengambil katalog produk penjual untuk AI prompt: {e}")

    system_prompt = build_system_prompt(
        store_name,
        product_contexts,
        knowledges_by_product,
        bot_name=bot_name,
        general_knowledges=general_knowledges,
        real_products=real_products,
    )

    recent_msgs = session.messages.exclude(id=user_msg.id).order_by("-created_at")[:8]
    recent_msgs = reversed(recent_msgs)

    messages_payload = [{"role": "system", "content": system_prompt}]
    for m in recent_msgs:
        role = "user" if m.sender_type == ChatMessage.SENDER_BUYER else "assistant"
        messages_payload.append({"role": role, "content": m.content})
    messages_payload.append({"role": "user", "content": content})

    try:
        raw_ai_reply = query_openrouter(messages_payload)
    except Exception as e:
        logger.error(f"Gagal memanggil AI service: {e}")
        # Fallback kalo API error/offline: chat langsung ke penjual
        direct_session = _transfer_to_direct_session(
            session,
            reason=ChatSession.HANDOVER_UNANSWERED,
            forward_question=content
        )
        return JsonResponse({
            "status": "success",
            "handover": True,
            "direct_session_id": str(direct_session.id),
            "reply": "Layanan AI asisten sedang sibuk. Pertanyaan Anda telah otomatis kami teruskan ke ruang obrolan langsung dengan penjual.",
        })

    is_handover, cleaned_reply = parse_handover_signal(raw_ai_reply)

    if is_handover:
        direct_session = _transfer_to_direct_session(
            session,
            reason=ChatSession.HANDOVER_UNANSWERED,
            forward_question=content
        )
        return JsonResponse({
            "status": "success",
            "handover": True,
            "direct_session_id": str(direct_session.id),
            "reply": cleaned_reply,
            "message": "Jawaban tidak ada di daftar penjual. Sesi dialihkan ke chat langsung dengan penjual.",
        })

    ai_msg = ChatMessage.objects.create(
        session=session,
        sender=None,
        sender_type=ChatMessage.SENDER_AI,
        content=cleaned_reply,
    )

    return JsonResponse({
        "status": "success",
        "handover": False,
        "reply": cleaned_reply,
        "message_id": str(ai_msg.id),
        "session_id": str(session.id),
    })


@login_required
def escalate_to_seller_api(request, session_id):
    """
    Mengalihkan sesi AI aktif ke ruang obrolan langsung (direct chat) dengan penjual atas permintaan pembeli.

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/escalate-to-seller/`

    Alur:
    1. Validasi sesi bertipe AI dan pengirim adalah pembeli.
    2. Panggil helper `_transfer_to_direct_session(reason=HANDOVER_MANUAL)`.
    3. Seluruh riwayat obrolan AI disalin ke sesi direct baru.
    4. Sesi AI lama ditandai `resolved`.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan AI target.

    Returns:
        JsonResponse: Detail status keberhasilan dan `direct_session_id` untuk redirect frontend.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli di sesi ini yang dapat beralih ke penjual.", status=403)

    if session.session_type != ChatSession.TYPE_AI:
        return _json_error("Sesi ini sudah bukan sesi AI.")

    if session.status != ChatSession.STATUS_ACTIVE:
        return _json_error("Sesi AI ini sudah selesai dan tidak dapat dialihkan lagi.", status=400)

    direct_session = _transfer_to_direct_session(
        session,
        reason=ChatSession.HANDOVER_MANUAL
    )

    return JsonResponse({
        "status": "success",
        "handover": True,
        "direct_session_id": str(direct_session.id),
        "message": "Sesi chat baru langsung dengan penjual berhasil dibuat.",
    })


@login_required
def switch_to_ai_session_api(request, session_id):
    """
    Mengalihkan sesi obrolan langsung (direct) kembali ke sesi asisten AI bot toko.

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/switch-to-ai/`

    Alur:
    1. Validasi sesi bertipe direct dan pengirim adalah pembeli.
    2. Panggil helper `_transfer_to_ai_session(direct_session)`.
    3. Seluruh riwayat pesan direct disalin ke sesi AI baru.
    4. Sesi direct lama ditandai `resolved`.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan direct target.

    Returns:
        JsonResponse: Detail status keberhasilan dan `ai_session_id` untuk redirect frontend.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Akses ditolak. Hanya pembeli yang dapat beralih ke asisten AI.", status=403)

    if session.session_type != ChatSession.TYPE_DIRECT:
        return _json_error("Sesi ini sudah merupakan sesi asisten AI.", status=400)

    if session.status != ChatSession.STATUS_ACTIVE:
        return _json_error("Sesi obrolan langsung ini sudah selesai.", status=400)

    ai_session = _transfer_to_ai_session(session)

    chat_settings = _get_seller_chat_settings(session.seller)
    bot_name = chat_settings.bot_name if (chat_settings and chat_settings.bot_name) else "Asisten Toko"

    return JsonResponse({
        "status": "success",
        "message": f"Berhasil beralih kembali ke Asisten AI ({bot_name}).",
        "ai_session_id": str(ai_session.id),
        "session_type": ai_session.session_type,
    })


# ==============================================================================
# GENERAL & DIRECT CHAT API
# ==============================================================================

@login_required
def get_session_messages_api(request, session_id):
    """
    Mengambil seluruh pesan dalam suatu sesi obrolan (AI atau Direct), serta memperbarui status baca pesan.

    Metode: GET
    Endpoint: `/chat/api/sessions/<session_id>/messages/`

    Alur:
    1. Validasi hak akses (harus buyer atau seller dari sesi tersebut, atau admin/staff).
    2. Menandai pesan masuk yang belum dibaca sebagai `is_read=True`:
       - Jika pembeli membuka: tandai pesan seller/AI sebagai terbaca.
       - Jika penjual membuka: tandai pesan buyer sebagai terbaca.
    3. Serialisasi daftar pesan, info metadata sesi, konteks produk, dan data rating (jika ada).

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan target.

    Returns:
        JsonResponse: Detail lengkap sesi dan array pesan (`messages`).
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller) and not request.user.is_staff:
        return _json_error("Anda tidak memiliki akses ke sesi ini.", status=403)

    # Tandain pesan yang diterima sebagai sudah dibaca
    if request.user == session.buyer:
        session.messages.exclude(sender_type=ChatMessage.SENDER_BUYER).filter(is_read=False).update(is_read=True)
    elif request.user == session.seller:
        session.messages.filter(sender_type=ChatMessage.SENDER_BUYER, is_read=False).update(is_read=True)

    messages_qs = session.messages.order_by("created_at")
    messages_data = [
        {
            "id": str(m.id),
            "sender_type": m.sender_type,
            "sender_email": m.sender.email if m.sender else None,
            "sender_name": m.sender.full_name if m.sender else ("AI Assistant" if m.sender_type == "ai" else "Sistem"),
            "content": m.content,
            "is_inherited_from_ai": m.is_inherited_from_ai,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages_qs
    ]

    contexts = [
        {"product_id": c.product_id, "product_name": c.product_name}
        for c in session.product_contexts.all()
    ]

    rating_data = None
    if hasattr(session, 'rating'):
        rating_data = {
            "rating": session.rating.rating,
            "feedback": session.rating.feedback,
            "created_at": session.rating.created_at.isoformat(),
        }

    return JsonResponse({
        "status": "success",
        "session": {
            "id": str(session.id),
            "session_type": session.session_type,
            "status": session.status,
            "handover_reason": session.handover_reason,
            "origin_session_id": str(session.origin_session_id) if session.origin_session_id else None,
            "is_archived_by_buyer": session.is_archived_by_buyer,
            "is_archived_by_seller": session.is_archived_by_seller,
            "buyer": {"id": session.buyer.id, "email": session.buyer.email, "name": session.buyer.full_name},
            "seller": {
                "id": session.seller.id,
                "email": session.seller.email,
                "store_name": _get_seller_store_name(session.seller),
            },
            "product_contexts": contexts,
            "rating": rating_data,
        },
        "messages": messages_data,
    })


@login_required
def send_direct_message_api(request, session_id):
    """
    Mengirimkan pesan pada sesi obrolan langsung manusia (direct chat antara penjual dan pembeli).

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/direct-send/`

    Payload JSON:
    ```json
    {"content": "Halo kak, stok barang ini ready banyak ya."}
    ```

    Alur:
    1. Validasi sesi bertipe `TYPE_DIRECT` dan pengguna merupakan partisipan sah.
    2. Tentukan `sender_type`: 'buyer' jika pengirim adalah pembeli, atau 'seller' jika penjual.
    3. Simpan pesan baru ke database (`ChatMessage`).
    4. Perbarui timestamp sesi `updated_at`.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan direct target.

    Returns:
        JsonResponse: Objek pesan yang baru tersimpan (`message`).
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller):
        return _json_error("Akses ditolak.", status=403)

    if session.session_type != ChatSession.TYPE_DIRECT:
        return _json_error("Endpoint ini hanya untuk sesi obrolan langsung (direct).", status=400)

    if session.status != ChatSession.STATUS_ACTIVE:
        return _json_error("Sesi obrolan ini sudah selesai dan tidak dapat menerima pesan baru.", status=400)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    content = str(data.get("content", "")).strip()
    if not content:
        return _json_error("Content pesan tidak boleh kosong.")

    sender_type = ChatMessage.SENDER_BUYER if request.user == session.buyer else ChatMessage.SENDER_SELLER

    msg = ChatMessage.objects.create(
        session=session,
        sender=request.user,
        sender_type=sender_type,
        content=content,
        is_inherited_from_ai=False,
        is_read=False,
    )

    session.save(update_fields=["updated_at"])

    return JsonResponse({
        "status": "success",
        "message": {
            "id": str(msg.id),
            "sender_type": msg.sender_type,
            "sender_email": request.user.email,
            "content": msg.content,
            "is_inherited_from_ai": msg.is_inherited_from_ai,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
        }
    })


@login_required
def toggle_archive_session_api(request, session_id):
    """
    Mengubah status arsip (archive / unarchive) sesi obrolan secara independen untuk buyer atau seller.

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/archive/`

    Alur:
    - Jika pembeli yang memanggil: toggle kolom `is_archived_by_buyer`.
    - Jika penjual yang memanggil: toggle kolom `is_archived_by_seller`.
    - Mengarsipkan tidak menghapus obrolan dan tidak mempengaruhi tampilan pihak lawan.

    Args:
        request (HttpRequest): Request pengguna.
        session_id (str|UUID): ID percakapan target.

    Returns:
        JsonResponse: Objek status arsip terbaru `{"status": "success", "is_archived": bool}`.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user == session.buyer:
        session.is_archived_by_buyer = not session.is_archived_by_buyer
        session.save(update_fields=["is_archived_by_buyer"])
        return JsonResponse({"status": "success", "is_archived": session.is_archived_by_buyer})
    elif request.user == session.seller:
        session.is_archived_by_seller = not session.is_archived_by_seller
        session.save(update_fields=["is_archived_by_seller"])
        return JsonResponse({"status": "success", "is_archived": session.is_archived_by_seller})

    return _json_error("Akses ditolak.", status=403)


# ==============================================================================
# INBOX API (BUYER & SELLER)
# ==============================================================================

@login_required
def buyer_inbox_sessions_api(request):
    """
    Mengambil daftar riwayat percakapan milik pembeli untuk ditampilkan pada sidebar inbox.

    Metode: GET
    Endpoint: `/chat/api/inbox/buyer/?tab=<tab>&search=<search>`

    Filter Tab:
    - `semua`: Sesi aktif (tidak diarsipkan) dan bukan sesi resolved.
    - `belum_dibaca`: Sesi dengan pesan masuk dari seller/AI yang belum dibaca.
    - `diarsipkan`: Sesi yang telah diarsipkan oleh pembeli.

    Fitur Utama:
    - Deduplikasi toko: Satu toko hanya muncul 1 kali (sesi paling mutakhir).
    - Pencarian nama toko atau isi pesan terakhir.
    - Hitung unread count dan lampirkan konteks produk terkait.

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        JsonResponse: Objek respons JSON `{"status": "success", "sessions": [...]}`.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    buyer = request.user
    tab = request.GET.get("tab", "semua").lower()
    search = request.GET.get("search", "").strip().lower()

    # Sesi aktif pembeli (sesi resolved yang telah dialihkan tidak ditampilkan)
    sessions_qs = ChatSession.objects.filter(buyer=buyer).exclude(
        status=ChatSession.STATUS_RESOLVED,
    ).order_by("-updated_at")

    if tab == "diarsipkan":
        sessions_qs = sessions_qs.filter(is_archived_by_buyer=True)
    else:
        sessions_qs = sessions_qs.filter(is_archived_by_buyer=False)
        if tab == "belum_dibaca":
            sessions_qs = sessions_qs.filter(
                messages__sender_type__in=[ChatMessage.SENDER_SELLER, ChatMessage.SENDER_AI],
                messages__is_read=False
            ).distinct()

    seen_seller_ids = set()
    results = []
    for s in sessions_qs:
        # Deduplikasi: satu toko hanya muncul satu kali pada daftar sesi pembeli (sesi terbaru)
        if s.seller_id in seen_seller_ids:
            continue
        seen_seller_ids.add(s.seller_id)

        last_msg = s.messages.order_by("-created_at").first()
        store_name = _get_seller_store_name(s.seller)

        if search:
            match_store = search in store_name.lower() or search in s.seller.email.lower()
            match_msg = last_msg and search in last_msg.content.lower()
            if not (match_store or match_msg):
                continue

        unread_count = s.messages.filter(
            sender_type__in=[ChatMessage.SENDER_SELLER, ChatMessage.SENDER_AI],
            is_read=False
        ).count()
        contexts = [
            {"product_id": c.product_id, "product_name": c.product_name}
            for c in s.product_contexts.all()
        ]

        results.append({
            "id": str(s.id),
            "session_type": s.session_type,
            "status": s.status,
            "seller": {
                "id": s.seller.id,
                "email": s.seller.email,
                "store_name": store_name,
            },
            "unread_count": unread_count,
            "is_archived": s.is_archived_by_buyer,
            "product_contexts": contexts,
            "last_message": {
                "content": last_msg.content if last_msg else None,
                "sender_type": last_msg.sender_type if last_msg else None,
                "created_at": last_msg.created_at.isoformat() if last_msg else None,
            } if last_msg else None,
            "updated_at": s.updated_at.isoformat(),
        })

    return JsonResponse({
        "status": "success",
        "tab": tab,
        "total_sessions": len(results),
        "sessions": results,
    })


@login_required
def seller_inbox_sessions_api(request):
    """
    Mengambil daftar percakapan langsung pembeli pada dashboard inbox penjual.

    Metode: GET
    Endpoint: `/chat/api/inbox/seller/?tab=<tab>&search=<search>`

    Filter Tab:
    - `semua`: Seluruh sesi obrolan direct pembeli aktif.
    - `belum_dibaca`: Sesi yang memiliki pesan pembeli berstatus `is_read=False`.
    - `belum_dibalas`: Sesi di mana pesan terakhir dikirimkan oleh pembeli (belum ada balasan dari seller).

    Fitur Utama:
    - Deduplikasi buyer: Setiap pembeli unik hanya muncul 1 kali pada list (sesi paling baru).
    - Pencarian nama pembeli atau isi pesan obrolan.

    Args:
        request (HttpRequest): Request pengguna (penjual).

    Returns:
        JsonResponse: Objek respons JSON `{"status": "success", "sessions": [...]}`.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    seller = request.user
    tab = request.GET.get("tab", "semua").lower()
    search = request.GET.get("search", "").strip().lower()

    sessions_qs = ChatSession.objects.filter(
        seller=seller,
        session_type=ChatSession.TYPE_DIRECT,
        status=ChatSession.STATUS_ACTIVE,
        is_archived_by_seller=False
    ).order_by("-updated_at")

    if tab == "belum_dibaca":
        sessions_qs = sessions_qs.filter(
            messages__sender_type=ChatMessage.SENDER_BUYER,
            messages__is_read=False
        ).distinct()

    seen_buyer_ids = set()
    results = []
    for s in sessions_qs:
        # Deduplikasi: satu pembeli hanya muncul satu kali pada inbox penjual (sesi terbaru)
        if s.buyer_id in seen_buyer_ids:
            continue
        seen_buyer_ids.add(s.buyer_id)

        last_msg = s.messages.order_by("-created_at").first()

        if tab == "belum_dibalas":
            if not last_msg or last_msg.sender_type != ChatMessage.SENDER_BUYER:
                continue

        buyer_name = s.buyer.full_name or s.buyer.email.split('@')[0]
        if search:
            match_buyer = search in buyer_name.lower() or search in s.buyer.email.lower()
            match_msg = last_msg and search in last_msg.content.lower()
            if not (match_buyer or match_msg):
                continue

        unread_count = s.messages.filter(sender_type=ChatMessage.SENDER_BUYER, is_read=False).count()
        contexts = [
            {"product_id": c.product_id, "product_name": c.product_name}
            for c in s.product_contexts.all()
        ]

        results.append({
            "id": str(s.id),
            "status": s.status,
            "buyer": {
                "id": s.buyer.id,
                "email": s.buyer.email,
                "name": buyer_name,
            },
            "unread_count": unread_count,
            "product_contexts": contexts,
            "last_message": {
                "content": last_msg.content if last_msg else None,
                "sender_type": last_msg.sender_type if last_msg else None,
                "created_at": last_msg.created_at.isoformat() if last_msg else None,
            } if last_msg else None,
            "updated_at": s.updated_at.isoformat(),
        })

    return JsonResponse({
        "status": "success",
        "tab": tab,
        "total_sessions": len(results),
        "sessions": results,
    })


# ==============================================================================
# SELLER SETTINGS & KNOWLEDGE BASE MANAGEMENT
# ==============================================================================

@login_required
def seller_chat_settings_api(request):
    """
    Mengambil atau memperbarui pengaturan bot AI penjual (nama bot, pesan sambutan, pesan tutup, jam buka).

    Metode: GET | POST | PUT | PATCH
    Endpoint: `/chat/api/seller/settings/`

    Payload Simpan (POST/PUT/PATCH):
    ```json
    {
        "is_auto_reply_enabled": true,
        "bot_name": "EucalypBot",
        "welcome_message": "Halo! Ada yang bisa kami bantu seputar produk kami?",
        "operating_hours_start": "08:00",
        "operating_hours_end": "19:00",
        "closed_message": "Toko sedang tutup. Kami akan membalas di jam kerja."
    }
    ```

    Args:
        request (HttpRequest): Request pengguna (harus login).

    Returns:
        JsonResponse: Objek respons JSON berisi konfigurasi pengaturan bot terbaru.
    """
    settings_obj = _get_seller_chat_settings(request.user)

    if request.method == "GET":
        return JsonResponse({
            "status": "success",
            "settings": {
                "is_auto_reply_enabled": settings_obj.is_auto_reply_enabled,
                "bot_name": settings_obj.bot_name,
                "welcome_message": settings_obj.welcome_message,
                "operating_hours_start": _format_time_str(settings_obj.operating_hours_start),
                "operating_hours_end": _format_time_str(settings_obj.operating_hours_end),
                "closed_message": settings_obj.closed_message,
                "updated_at": settings_obj.updated_at.isoformat(),
            }
        })

    elif request.method in ("POST", "PUT", "PATCH"):
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return _json_error("Format JSON tidak valid.")

        if "is_auto_reply_enabled" in data:
            settings_obj.is_auto_reply_enabled = bool(data["is_auto_reply_enabled"])
        if "bot_name" in data:
            settings_obj.bot_name = str(data["bot_name"]).strip() or "BhumiBot"
        if "welcome_message" in data:
            settings_obj.welcome_message = str(data["welcome_message"]).strip()
        if "closed_message" in data:
            settings_obj.closed_message = str(data["closed_message"]).strip()

        if "operating_hours_start" in data:
            try:
                settings_obj.operating_hours_start = datetime.strptime(str(data["operating_hours_start"]).strip(), "%H:%M").time()
            except ValueError:
                return _json_error("Format operating_hours_start harus HH:MM (contoh 08:00).")

        if "operating_hours_end" in data:
            try:
                settings_obj.operating_hours_end = datetime.strptime(str(data["operating_hours_end"]).strip(), "%H:%M").time()
            except ValueError:
                return _json_error("Format operating_hours_end harus HH:MM (contoh 19:00).")

        settings_obj.save()

        return JsonResponse({
            "status": "success",
            "message": "Pengaturan bot berhasil disimpan.",
            "settings": {
                "is_auto_reply_enabled": settings_obj.is_auto_reply_enabled,
                "bot_name": settings_obj.bot_name,
                "welcome_message": settings_obj.welcome_message,
                "operating_hours_start": _format_time_str(settings_obj.operating_hours_start),
                "operating_hours_end": _format_time_str(settings_obj.operating_hours_end),
                "closed_message": settings_obj.closed_message,
            }
        })

    return _json_error("Metode tidak didukung.", status=405)


@login_required
def seller_knowledge_list_create_api(request):
    """
    Melihat daftar Q&A bot yang dimiliki penjual (GET) atau menambahkan Q&A baru (POST).

    Metode: GET | POST
    Endpoint: `/chat/api/seller/knowledges/`

    Query GET:
    `?product_id=<id>` (opsional: filter kata kunci hanya untuk produk tertentu).

    Payload POST:
    ```json
    {
        "product_id": "1",
        "product_name": "Sabun Bambu",
        "question": "Apakah sabun ini bebas paraben?",
        "answer": "Ya, 100% alami tanpa bahan kimia berbahaya.",
        "is_active": true
    }
    ```

    Args:
        request (HttpRequest): Request pengguna (penjual).

    Returns:
        JsonResponse: Daftar Q&A (`knowledges`) atau entri Q&A baru yang berhasil disimpan.
    """
    seller = request.user

    if request.method == "GET":
        qs = ProductKnowledge.objects.filter(seller=seller)
        product_id = request.GET.get("product_id")
        if product_id:
            qs = qs.filter(product_id=product_id)

        items = [
            {
                "id": k.id,
                "product_id": k.product_id,
                "product_name": k.product_name,
                "question": k.question,
                "answer": k.answer,
                "is_active": k.is_active,
                "created_at": k.created_at.isoformat(),
                "updated_at": k.updated_at.isoformat(),
            }
            for k in qs
        ]
        return JsonResponse({"status": "success", "total": len(items), "knowledges": items})

    elif request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return _json_error("Format JSON tidak valid.")

        raw_pid = data.get("product_id")
        product_id = str(raw_pid).strip() if raw_pid not in (None, "", "null") else None
        product_name = str(data.get("product_name", "")).strip()
        question = str(data.get("question", "")).strip()
        answer = str(data.get("answer", "")).strip()

        if not question or not answer:
            return _json_error("question dan answer wajib diisi.")

        item = ProductKnowledge.objects.create(
            seller=seller,
            product_id=product_id,
            product_name=product_name,
            question=question,
            answer=answer,
            is_active=bool(data.get("is_active", True)),
        )

        return JsonResponse({
            "status": "success",
            "message": "Knowledge Q&A berhasil ditambahkan.",
            "knowledge": {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "question": item.question,
                "answer": item.answer,
                "is_active": item.is_active,
            }
        }, status=201)

    return _json_error("Metode tidak didukung.", status=405)


@login_required
def seller_knowledge_detail_api(request, pk):
    """
    Mengambil detail (GET), mengubah (PUT/PATCH), atau menghapus (DELETE) satu entri Q&A bot.

    Metode: GET | PUT | PATCH | DELETE
    Endpoint: `/chat/api/seller/knowledges/<pk>/`

    Args:
        request (HttpRequest): Request pengguna (penjual pemilik Q&A).
        pk (int): Primary key ID dari entri `ProductKnowledge`.

    Returns:
        JsonResponse: Detail data Q&A atau notifikasi penghapusan.
    """
    item = get_object_or_404(ProductKnowledge, id=pk, seller=request.user)

    if request.method == "GET":
        return JsonResponse({
            "status": "success",
            "knowledge": {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "question": item.question,
                "answer": item.answer,
                "is_active": item.is_active,
            }
        })

    elif request.method in ("PUT", "PATCH"):
        try:
            data = json.loads(request.body.decode("utf-8")) if request.body else {}
        except json.JSONDecodeError:
            return _json_error("Format JSON tidak valid.")

        if "question" in data:
            item.question = str(data["question"]).strip()
        if "answer" in data:
            item.answer = str(data["answer"]).strip()
        if "product_name" in data:
            item.product_name = str(data["product_name"]).strip()
        if "product_id" in data:
            raw_pid = data["product_id"]
            item.product_id = str(raw_pid).strip() if raw_pid not in (None, "", "null") else None
        if "is_active" in data:
            item.is_active = bool(data["is_active"])

        item.save()
        return JsonResponse({
            "status": "success",
            "message": "Knowledge Q&A berhasil diperbarui.",
            "knowledge": {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "question": item.question,
                "answer": item.answer,
                "is_active": item.is_active,
            }
        })

    elif request.method == "DELETE":
        item.delete()
        return JsonResponse({
            "status": "success",
            "message": "Knowledge Q&A berhasil dihapus.",
        })

    return _json_error("Metode tidak didukung.", status=405)


@login_required
def seller_knowledge_toggle_api(request, pk):
    """
    Mengubah switch status aktif/nonaktif (`is_active`) untuk suatu entri Q&A bot penjual.

    Metode: POST
    Endpoint: `/chat/api/seller/knowledges/<pk>/toggle/`

    Args:
        request (HttpRequest): Request pengguna (penjual).
        pk (int): Primary key ID dari entri `ProductKnowledge`.

    Returns:
        JsonResponse: Objek status aktif terbaru `{"status": "success", "is_active": bool}`.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    item = get_object_or_404(ProductKnowledge, id=pk, seller=request.user)
    item.is_active = not item.is_active
    item.save(update_fields=["is_active"])

    return JsonResponse({
        "status": "success",
        "id": item.id,
        "is_active": item.is_active,
        "message": f"Kata kunci '{item.question}' sekarang {'aktif' if item.is_active else 'nonaktif'}."
    })


# ==============================================================================
# RATING & REPORT API (POPOVER FIGMA)
# ==============================================================================

@login_required
def submit_session_rating_api(request, session_id):
    """
    Mengirimkan penilaian bintang (1-5) dan ulasan teks kepuasan pembeli terhadap sesi percakapan.

    Metode: POST
    Endpoint: `/chat/api/sessions/<session_id>/rating/`

    Payload JSON:
    ```json
    {
        "rating": 5,
        "feedback": "Penjual sangat ramah dan responsif!"
    }
    ```

    Args:
        request (HttpRequest): Request pengguna (harus merupakan pembeli pada sesi tersebut).
        session_id (str|UUID): ID percakapan target.

    Returns:
        JsonResponse: Objek respons JSON berisi data rating yang tersimpan.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli yang dapat memberikan rating percakapan.", status=403)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    try:
        rating_val = int(data.get("rating", 5))
    except (TypeError, ValueError):
        return _json_error("Rating harus berupa angka 1 sampai 5.")

    if not 1 <= rating_val <= 5:
        return _json_error("Rating harus bernilai antara 1 sampai 5.")

    feedback_val = str(data.get("feedback", "")).strip()

    rating_obj, _ = SessionRating.objects.update_or_create(
        session=session,
        defaults={
            "user": request.user,
            "rating": rating_val,
            "feedback": feedback_val,
        }
    )

    return JsonResponse({
        "status": "success",
        "message": "Terima kasih atas rating dan feedback Anda!",
        "rating": {
            "session_id": str(session.id),
            "rating": rating_obj.rating,
            "feedback": rating_obj.feedback,
            "created_at": rating_obj.created_at.isoformat(),
        }
    })


@login_required
def submit_user_report_api(request):
    """
    Mengirimkan laporan pelanggaran akun pengguna (pembeli melaporkan penjual, atau penjual melaporkan pembeli).

    Metode: POST
    Endpoint: `/chat/api/reports/`

    Payload JSON:
    ```json
    {
        "reported_user_id": 2,
        "session_id": "060d40aa-...",
        "reason": "Pengguna menggunakan kata-kata kasar yang menyinggung."
    }
    ```

    Args:
        request (HttpRequest): Request pengguna (pelapor).

    Returns:
        JsonResponse: Konfirmasi pengiriman laporan (`report_id`) dan status HTTP 201 Created.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    reported_user_id = data.get("reported_user_id")
    reason = str(data.get("reason", "")).strip()

    if not reported_user_id or not reason:
        return _json_error("reported_user_id dan reason wajib diisi.")

    reported_user = get_object_or_404(User, id=reported_user_id)
    if reported_user == request.user:
        return _json_error("Anda tidak dapat melaporkan diri sendiri.")

    session = None
    session_id = data.get("session_id")
    if session_id:
        session = ChatSession.objects.filter(id=session_id).first()

    report = UserReport.objects.create(
        reporter=request.user,
        reported_user=reported_user,
        session=session,
        reason=reason,
    )

    return JsonResponse({
        "status": "success",
        "message": "Laporan Anda telah berhasil dikirimkan.",
        "report_id": report.id,
    }, status=201)


# ==============================================================================
# BROADCAST CHANNEL API (FIGMA BROADCAST SCREEN)
# ==============================================================================

def _ensure_all_sellers_have_broadcast_channels():
    """
    Helper untuk memastikan setiap user dengan role 'seller' otomatis memiliki tepat 1 BroadcastChannel resmi.
    Dipanggil saat membuka halaman siaran atau mengambil daftar channel.
    """
    sellers = User.objects.filter(role="seller").exclude(broadcast_channel__isnull=False)
    for s in sellers:
        store_name = _get_seller_store_name(s)
        channel_name = f"Channel {store_name}" if not store_name.lower().startswith("channel") else store_name
        BroadcastChannel.objects.get_or_create(
            seller=s,
            defaults={
                "name": channel_name,
                "description": f"Saluran pengumuman resmi {store_name}",
                "followers_count": 0,
            },
        )


@login_required
def list_broadcast_channels_api(request):
    """
    Mengambil daftar saluran broadcast (pengumuman toko).

    Metode: GET
    Endpoint: `/chat/api/broadcast/channels/?tab=<tab>&search=<search>`

    Logika Penyortiran Khusus:
    - Jika pengguna yang login adalah seller, channel miliknya sendiri diposisikan di urutan paling atas (`my_channel`).
    - Channel seller lain dikelompokkan terpisah (`other_channels`).
    - Filter tab 'semua' atau 'diarsipkan'.

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        JsonResponse: Objek respons JSON berisi `my_channel`, `other_channels`, dan `channels`.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    tab = request.GET.get("tab", "semua").lower()
    search = request.GET.get("search", "").strip().lower()

    _ensure_all_sellers_have_broadcast_channels()

    channels_qs = BroadcastChannel.objects.all().order_by("-followers_count")

    # Filter saluran: hanya tampilkan channel yang difollow, ditambahkan, atau dimiliki (jika seller)
    user_channels_filter = Q(followers=request.user) | Q(added_by=request.user)
    if getattr(request.user, "role", "") == "seller":
        user_channels_filter |= Q(seller=request.user)
    channels_qs = channels_qs.filter(user_channels_filter).distinct()

    if tab == "diarsipkan":
        channels_qs = channels_qs.filter(archived_by=request.user)
    else:
        channels_qs = channels_qs.exclude(archived_by=request.user)

    channels_list = list(channels_qs)
    if getattr(request.user, "role", "") == "seller":
        channels_list.sort(key=lambda c: 0 if c.seller_id == request.user.id else 1)

    results = []
    my_channel = None
    other_channels = []

    for c in channels_list:
        last_msg = c.messages.first() if c.messages.exists() else None
        if search:
            name_match = search in c.name.lower() or search in c.description.lower()
            msg_match = last_msg and search in last_msg.content.lower()
            if not (name_match or msg_match):
                continue

        is_archived = c.archived_by.filter(id=request.user.id).exists()
        is_owner = c.seller_id == request.user.id
        is_following = c.followers.filter(id=request.user.id).exists()
        item_data = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "seller_email": c.seller.email,
            "followers_count": c.followers_count,
            "is_archived": is_archived,
            "is_owner": is_owner,
            "is_following": is_following,
            "last_message": {
                "content": last_msg.content if last_msg else None,
                "created_at": last_msg.created_at.isoformat() if last_msg else None,
            }
        }
        results.append(item_data)
        if is_owner:
            my_channel = item_data
        else:
            other_channels.append(item_data)

    return JsonResponse({
        "status": "success",
        "tab": tab,
        "total": len(results),
        "my_channel": my_channel,
        "other_channels": other_channels,
        "channels": results,
    })


@login_required
def toggle_archive_broadcast_channel_api(request, channel_id):
    """
    Mengarsipkan atau membatalkan arsip saluran siaran untuk pengguna saat ini.

    Metode: POST
    Endpoint: `/chat/api/broadcast/channels/<channel_id>/archive/`

    Args:
        request (HttpRequest): Request pengguna.
        channel_id (int): ID saluran broadcast.

    Returns:
        JsonResponse: Status arsip terbaru `{"status": "success", "is_archived": bool}`.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    channel = get_object_or_404(BroadcastChannel, id=channel_id)
    if channel.archived_by.filter(id=request.user.id).exists():
        channel.archived_by.remove(request.user)
        is_archived = False
    else:
        channel.archived_by.add(request.user)
        is_archived = True

    return JsonResponse({
        "status": "success",
        "channel_id": channel.id,
        "is_archived": is_archived,
        "message": f"Channel {'diarsipkan' if is_archived else 'dikeluarkan dari arsip'}."
    })


@login_required
def toggle_follow_broadcast_channel_api(request, channel_id):
    """
    Mengikuti (follow) atau berhenti mengikuti (unfollow) saluran broadcast toko.

    Metode: POST
    Endpoint: `/chat/api/broadcast/channels/<channel_id>/follow/`

    Args:
        request (HttpRequest): Request pengguna.
        channel_id (int): ID saluran broadcast.

    Returns:
        JsonResponse: Status follow terbaru `{"status": "success", "is_following": bool, "followers_count": int}`.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    channel = get_object_or_404(BroadcastChannel, id=channel_id)
    if channel.seller == request.user:
        return _json_error("Anda tidak dapat mengikuti channel Anda sendiri.", status=400)

    if channel.followers.filter(id=request.user.id).exists():
        channel.followers.remove(request.user)
        is_following = False
    else:
        channel.followers.add(request.user)
        is_following = True

    channel.followers_count = channel.followers.count()
    channel.save(update_fields=["followers_count"])

    return JsonResponse({
        "status": "success",
        "channel_id": channel.id,
        "is_following": is_following,
        "followers_count": channel.followers_count,
        "message": f"Berhasil {'mengikuti' if is_following else 'berhenti mengikuti'} {channel.name}."
    })


@login_required
def explore_broadcast_channels_api(request):
    """
    Mencari dan merekomendasikan saluran siaran toko untuk ditambahkan pengguna ke daftar saluran mereka.

    Metode: GET
    Endpoint: `/chat/api/broadcast/channels/explore/?q=<query>`

    Alur:
    1. Memastikan semua penjual memiliki channel siaran resmi.
    2. Mengambil seluruh channel toko kecuali channel milik user sendiri.
    3. Jika terdapat parameter query 'q', memfilter berdasarkan nama channel, deskripsi, nama toko, atau nama penjual.
    4. Jika 'q' kosong, mengembalikan rekomendasi channel dengan pengikut terbanyak.
    5. Menyertakan informasi apakah channel sudah ada di list (`is_added`) atau sudah di-follow (`is_following`).

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        JsonResponse: Objek respons JSON berisi daftar channel toko yang tersedia.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    _ensure_all_sellers_have_broadcast_channels()

    q = request.GET.get("q", "").strip()

    channels_qs = BroadcastChannel.objects.exclude(seller=request.user)
    if q:
        channels_qs = channels_qs.filter(
            Q(name__icontains=q) |
            Q(description__icontains=q) |
            Q(seller__full_name__icontains=q) |
            Q(seller__seller_profile__store_name__icontains=q)
        ).distinct()[:15]
    else:
        channels_qs = channels_qs.order_by("-followers_count")[:15]

    results = []
    for c in channels_qs:
        store_name = _get_seller_store_name(c.seller)
        is_following = c.followers.filter(id=request.user.id).exists()
        is_added = c.added_by.filter(id=request.user.id).exists()
        results.append({
            "id": c.id,
            "name": c.name,
            "store_name": store_name,
            "description": c.description,
            "followers_count": c.followers_count,
            "is_following": is_following,
            "is_added": is_added,
        })

    return JsonResponse({
        "status": "success",
        "total": len(results),
        "channels": results,
    })


@login_required
def add_broadcast_channel_to_list_api(request, channel_id):
    """
    Menambahkan saluran siaran toko ke daftar saluran (channel list) pengguna.
    Sesuai kebutuhan: Saluran yang ditambahkan TIDAK otomatis terfollow, namun langsung
    masuk ke dalam daftar channel pengguna agar dapat dilihat/diakses.

    Metode: POST
    Endpoint: `/chat/api/broadcast/channels/<channel_id>/add/`

    Args:
        request (HttpRequest): Request pengguna.
        channel_id (int): ID saluran siaran yang akan ditambahkan.

    Returns:
        JsonResponse: Data saluran siaran yang berhasil ditambahkan ke daftar pengguna.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    channel = get_object_or_404(BroadcastChannel, id=channel_id)
    if channel.seller == request.user:
        return _json_error("Ini adalah saluran toko Anda sendiri.", status=400)

    # Tambahkan ke daftar channel pengguna tanpa mem-follow
    channel.added_by.add(request.user)

    is_following = channel.followers.filter(id=request.user.id).exists()
    is_archived = channel.archived_by.filter(id=request.user.id).exists()

    return JsonResponse({
        "status": "success",
        "channel": {
            "id": channel.id,
            "name": channel.name,
            "description": channel.description,
            "followers_count": channel.followers_count,
            "is_owner": False,
            "is_following": is_following,
            "is_archived": is_archived,
        },
        "message": f"Saluran {channel.name} berhasil ditambahkan ke daftar channel Anda."
    })


@login_required
def get_broadcast_messages_api(request, channel_id):
    """
    Mengambil seluruh pesan siaran pada suatu channel dan menaikkan hitungan viewed_count.

    Metode: GET
    Endpoint: `/chat/api/broadcast/channels/<channel_id>/messages/`

    Fitur:
    - Jika pengguna yang membaca bukan pemilik (seller) channel tersebut,
      naikkan hitungan `viewed_count` secara atomik (`F('viewed_count') + 1`).
    - Kembalikan status kepemilikan `is_owner` dan status `is_following`.

    Args:
        request (HttpRequest): Request pengguna.
        channel_id (int): ID saluran broadcast.

    Returns:
        JsonResponse: Objek respons JSON berisi detail channel dan array pesan siaran.
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    channel = get_object_or_404(BroadcastChannel, id=channel_id)
    messages_qs = channel.messages.all()

    # Naikkan view count
    if request.user != channel.seller:
        messages_qs.update(viewed_count=F('viewed_count') + 1)

    messages = [
        {
            "id": m.id,
            "content": m.content,
            "viewed_count": m.viewed_count,
            "created_at": m.created_at.isoformat(),
        }
        for m in channel.messages.all()
    ]

    is_archived = channel.archived_by.filter(id=request.user.id).exists()
    is_following = channel.followers.filter(id=request.user.id).exists()

    return JsonResponse({
        "status": "success",
        "channel": {
            "id": channel.id,
            "name": channel.name,
            "followers_count": channel.followers_count,
            "is_owner": request.user == channel.seller,
            "is_archived": is_archived,
            "is_following": is_following,
        },
        "messages": messages,
    })


@login_required
def send_broadcast_message_api(request, channel_id):
    """
    Mengirimkan pesan siaran / pengumuman baru ke saluran broadcast (khusus pemilik channel).

    Metode: POST
    Endpoint: `/chat/api/broadcast/channels/<channel_id>/messages/`

    Payload JSON:
    ```json
    {"content": "Dapatkan diskon 20% produk organik akhir pekan ini!"}
    ```

    Keamanan:
    - Hanya user yang merupakan penjual pemilik channel (`request.user == channel.seller`)
      yang diperkenankan memposting pesan broadcast. User lain akan ditolak dengan HTTP 403 Forbidden.

    Args:
        request (HttpRequest): Request pengguna (penjual pemilik channel).
        channel_id (int): ID saluran broadcast.

    Returns:
        JsonResponse: Pesan siaran baru yang tersimpan (`message`) dan status HTTP 201 Created.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    channel = get_object_or_404(BroadcastChannel, id=channel_id)
    if request.user != channel.seller:
        return _json_error("Anda tidak memiliki akses untuk mengirim pesan pada channel ini.", status=403)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except json.JSONDecodeError:
        return _json_error("Format JSON tidak valid.")

    content = str(data.get("content", "")).strip()
    if not content:
        return _json_error("Content siaran tidak boleh kosong.")

    b_msg = BroadcastMessage.objects.create(
        channel=channel,
        content=content,
        viewed_count=0,
    )

    return JsonResponse({
        "status": "success",
        "message": {
            "id": b_msg.id,
            "content": b_msg.content,
            "viewed_count": b_msg.viewed_count,
            "created_at": b_msg.created_at.isoformat(),
        }
    }, status=201)


# ==============================================================================
# FRONTEND TEMPLATE VIEWS (FIGMA 1:1 UI)
# ==============================================================================

@login_required
def buyer_chat_view(request):
    """
    Menampilkan antarmuka obrolan utama untuk pembeli (Screen 1-6 Figma).

    Konteks Template:
    - `sellers`: Daftar seluruh penjual untuk autocomplete popup pencarian.
    - `initial_seller_id`, `initial_product_id`, `initial_product_name`: Parameter query URL jika pembeli
      datang dari tombol "Chat Penjual" di halaman katalog produk.

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        HttpResponse: Template HTML yang dirender (`chat/buyer_chat.html`).
    """
    sellers_qs = User.objects.filter(role="seller").exclude(id=request.user.id)
    sellers = [
        {
            "id": s.id,
            "email": s.email,
            "store_name": _get_seller_store_name(s),
        }
        for s in sellers_qs
    ]

    context = {
        "active_nav": "chat",
        "is_seller_mode": False,
        "sellers": sellers,
        "initial_seller_id": request.GET.get("seller_id", ""),
        "initial_product_id": request.GET.get("product_id", ""),
        "initial_product_name": request.GET.get("product_name", ""),
    }
    return render(request, "chat/buyer_chat.html", context)


@login_required
def seller_chat_view(request):
    """
    Menampilkan antarmuka inbox obrolan langsung untuk penjual (Screen 10-12 Figma).

    Args:
        request (HttpRequest): Request pengguna (penjual).

    Returns:
        HttpResponse: Template HTML yang dirender (`chat/seller_chat.html`).
    """
    context = {
        "active_nav": "chat",
        "is_seller_mode": True,
    }
    return render(request, "chat/seller_chat.html", context)


@login_required
def seller_settings_view(request):
    """
    Menampilkan antarmuka pengaturan bot sambutan & jam operasional toko penjual (Screen 13 Figma).

    Args:
        request (HttpRequest): Request pengguna (penjual).

    Returns:
        HttpResponse: Template HTML yang dirender (`chat/seller_settings.html`).
    """
    chat_settings = _get_seller_chat_settings(request.user)
    context = {
        "active_nav": "settings",
        "active_subnav": "welcome",
        "is_seller_mode": True,
        "chat_settings": chat_settings,
        "operating_hours_start": _format_time_str(chat_settings.operating_hours_start),
        "operating_hours_end": _format_time_str(chat_settings.operating_hours_end),
    }
    return render(request, "chat/seller_settings.html", context)


@login_required
def seller_keywords_view(request):
    """
    Menampilkan antarmuka pengelolaan kata kunci & Q&A basis pengetahuan bot AI toko (Screen 14 Figma).

    Args:
        request (HttpRequest): Request pengguna (penjual).

    Returns:
        HttpResponse: Template HTML yang dirender (`chat/seller_keywords.html`).
    """
    chat_settings = _get_seller_chat_settings(request.user)
    knowledges = ProductKnowledge.objects.filter(seller=request.user)
    context = {
        "active_nav": "settings",
        "active_subnav": "keywords",
        "is_seller_mode": True,
        "chat_settings": chat_settings,
        "knowledges": knowledges,
    }
    return render(request, "chat/seller_keywords.html", context)


@login_required
def broadcast_view(request):
    """
    Menampilkan antarmuka saluran siaran / pengumuman (Screen 9 Figma).

    Args:
        request (HttpRequest): Request pengguna.

    Returns:
        HttpResponse: Template HTML yang dirender (`chat/broadcast.html`).
    """
    _ensure_all_sellers_have_broadcast_channels()
    is_seller = getattr(request.user, "role", "") == "seller"
    context = {
        "active_nav": "broadcast",
        "is_seller_mode": is_seller,
    }
    return render(request, "chat/broadcast.html", context)

