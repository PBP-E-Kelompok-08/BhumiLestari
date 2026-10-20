import json
import logging
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt 
from django.contrib.auth import get_user_model

from apps.chat.models import (
    ProductKnowledge,
    ChatSession,
    SessionProductContext,
    ChatMessage,
    SellerChatSettings,
    SessionRating,
    UserReport,
)
from apps.chat.services.ai_service import (
    build_system_prompt,
    query_openrouter,
    parse_handover_signal,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _json_error(message, status=400):
    return JsonResponse({"status": "error", "message": message}, status=status)


def _get_seller_store_name(seller):
    if hasattr(seller, 'seller_profile') and seller.seller_profile:
        return seller.seller_profile.store_name
    return seller.full_name or seller.email.split('@')[0]


def _transfer_to_direct_session(ai_session, reason=ChatSession.HANDOVER_MANUAL, forward_question=None):

    direct_session = ChatSession.objects.create(
        buyer=ai_session.buyer,
        seller=ai_session.seller,
        session_type=ChatSession.TYPE_DIRECT,
        status=ChatSession.STATUS_ACTIVE,
        origin_session=ai_session,
        handover_reason=reason,
    )

    for p_ctx in ai_session.product_contexts.all():
        SessionProductContext.objects.get_or_create(
            session=direct_session,
            product_id=p_ctx.product_id,
            defaults={"product_name": p_ctx.product_name}
        )

    ai_messages = ai_session.messages.order_by("created_at")
    for msg in ai_messages:
        ChatMessage.objects.create(
            session=direct_session,
            sender=msg.sender,
            sender_type=msg.sender_type,
            content=msg.content,
            is_inherited_from_ai=True,
            created_at=msg.created_at,
        )

    store_name = _get_seller_store_name(ai_session.seller)
    ChatMessage.objects.create(
        session=direct_session,
        sender=None,
        sender_type=ChatMessage.SENDER_SYSTEM,
        content=f"--- Anda kini terhubung langsung dengan penjual ({store_name}). Riwayat obrolan dengan AI tersimpan di atas. ---",
        is_inherited_from_ai=False,
    )

    if forward_question:
        ChatMessage.objects.create(
            session=direct_session,
            sender=ai_session.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content=forward_question,
            is_inherited_from_ai=False,
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
    )

    return direct_session


# ==============================================================================
# BUYER & AI CHAT API
# ==============================================================================

@login_required
def get_or_create_ai_session_api(request):
    """
    POST: Inisiasi sesi chat AI untuk satu atau lebih produk.
    Payload:
    {
        "seller_id": 1,
        "products": [
            {"product_id": "PRD-01", "product_name": "Sabun Bambu"},
            {"product_id": "PRD-02", "product_name": "Sikat Gigi"}
        ]
    }
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

    # Cari sesi AI aktif yang sudah ada dengan penjual tersebut
    ai_session = ChatSession.objects.filter(
        buyer=buyer,
        seller=seller,
        session_type=ChatSession.TYPE_AI,
        status=ChatSession.STATUS_ACTIVE,
    ).first()

    if not ai_session:
        ai_session = ChatSession.objects.create(
            buyer=buyer,
            seller=seller,
            session_type=ChatSession.TYPE_AI,
            status=ChatSession.STATUS_ACTIVE,
        )

    # Daftarkan konteks produk
    products = data.get("products", [])
    for p in products:
        p_id = str(p.get("product_id", "")).strip()
        p_name = str(p.get("product_name", "")).strip()
        if p_id:
            SessionProductContext.objects.get_or_create(
                session=ai_session,
                product_id=p_id,
                defaults={"product_name": p_name}
            )

    contexts = [
        {"product_id": c.product_id, "product_name": c.product_name}
        for c in ai_session.product_contexts.all()
    ]

    return JsonResponse({
        "status": "success",
        "session_id": str(ai_session.id),
        "session_type": ai_session.session_type,
        "seller": {
            "id": seller.id,
            "email": seller.email,
            "store_name": _get_seller_store_name(seller),
        },
        "product_contexts": contexts,
    })


@login_required
def add_product_context_api(request, session_id):
    """
    Payload:
    {
        "products": [{"product_id": "PRD-03", "product_name": "stuff or product or whatever"}]
    }
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller):
        return _json_error("Akses ditolak.", status=403)

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


@login_required
def send_ai_message_api(request, session_id):

    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli di sesi ini yang dapat mengirim pesan ke AI.", status=403)

    if session.session_type != ChatSession.TYPE_AI:
        return _json_error("Sesi ini bukan sesi AI. Gunakan endpoint direct-send.", status=400)

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
    )

    product_contexts = list(session.product_contexts.all())
    product_ids = [c.product_id for c in product_contexts]

    knowledges = ProductKnowledge.objects.filter(
        seller=session.seller,
        product_id__in=product_ids,
        is_active=True
    )
    knowledges_by_product = {}
    for k in knowledges:
        knowledges_by_product.setdefault(k.product_id, []).append(k)

    store_name = _get_seller_store_name(session.seller)
    system_prompt = build_system_prompt(store_name, product_contexts, knowledges_by_product)

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

    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli di sesi ini yang dapat beralih ke penjual.", status=403)

    if session.session_type != ChatSession.TYPE_AI:
        return _json_error("Sesi ini sudah bukan sesi AI.")

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


# ==============================================================================
# GENERAL & DIRECT CHAT API
# ==============================================================================

@login_required
def get_session_messages_api(request, session_id):

    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller) and not request.user.is_staff:
        return _json_error("Anda tidak memiliki akses ke sesi ini.", status=403)

    messages_qs = session.messages.order_by("created_at")
    messages_data = [
        {
            "id": str(m.id),
            "sender_type": m.sender_type,
            "sender_email": m.sender.email if m.sender else None,
            "sender_name": m.sender.full_name if m.sender else ("AI Assistant" if m.sender_type == "ai" else "Sistem"),
            "content": m.content,
            "is_inherited_from_ai": m.is_inherited_from_ai,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages_qs
    ]

    contexts = [
        {"product_id": c.product_id, "product_name": c.product_name}
        for c in session.product_contexts.all()
    ]

    return JsonResponse({
        "status": "success",
        "session": {
            "id": str(session.id),
            "session_type": session.session_type,
            "status": session.status,
            "handover_reason": session.handover_reason,
            "origin_session_id": str(session.origin_session_id) if session.origin_session_id else None,
            "buyer": {"id": session.buyer.id, "email": session.buyer.email, "name": session.buyer.full_name},
            "seller": {
                "id": session.seller.id,
                "email": session.seller.email,
                "store_name": _get_seller_store_name(session.seller),
            },
            "product_contexts": contexts,
        },
        "messages": messages_data,
    })


@login_required
def send_direct_message_api(request, session_id):
    """
    Payload: {"content": "ini chat ke penjual"}
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user not in (session.buyer, session.seller):
        return _json_error("Akses ditolak.", status=403)

    if session.session_type != ChatSession.TYPE_DIRECT:
        return _json_error("Endpoint ini hanya untuk sesi obrolan langsung (direct).", status=400)

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
    )

    return JsonResponse({
        "status": "success",
        "message": {
            "id": str(msg.id),
            "sender_type": msg.sender_type,
            "sender_email": request.user.email,
            "content": msg.content,
            "is_inherited_from_ai": msg.is_inherited_from_ai,
            "created_at": msg.created_at.isoformat(),
        }
    })


# ==============================================================================
# SELLER INBOX & KNOWLEDGE BASE MANAGEMENT API
# ==============================================================================

@login_required
def toggle_archive_session_api(request, session_id):
    """
    POST: Mengarsipkan atau membatalkan arsip sesi chat.
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
    GET: Daftar sesi chat pembeli sesuai filter tab:
    ?tab=semua | belum_dibaca | diarsipkan
    ?search=...
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    buyer = request.user
    tab = request.GET.get("tab", "semua").lower()
    search = request.GET.get("search", "").strip().lower()

    sessions_qs = ChatSession.objects.filter(buyer=buyer).order_by("-updated_at")

    if tab == "diarsipkan":
        sessions_qs = sessions_qs.filter(is_archived_by_buyer=True)
    else:
        sessions_qs = sessions_qs.filter(is_archived_by_buyer=False)
        if tab == "belum_dibaca":
            sessions_qs = sessions_qs.filter(
                messages__is_read=False
            ).exclude(messages__sender_type=ChatMessage.SENDER_BUYER).distinct()

    results = []
    for s in sessions_qs:
        last_msg = s.messages.order_by("-created_at").first()
        store_name = _get_seller_store_name(s.seller)

        if search:
            match_store = search in store_name.lower() or search in s.seller.email.lower()
            match_msg = last_msg and search in last_msg.content.lower()
            if not (match_store or match_msg):
                continue

        unread_count = s.messages.filter(is_read=False).exclude(sender_type=ChatMessage.SENDER_BUYER).count()
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
    GET: Penjual melihat daftar sesi chat langsung dari para pembeli sesuai filter tab:
    ?tab=semua | belum_dibaca | belum_dibalas
    ?search=...
    """
    if request.method != "GET":
        return _json_error("Hanya metode GET yang diizinkan.", status=405)

    seller = request.user
    tab = request.GET.get("tab", "semua").lower()
    search = request.GET.get("search", "").strip().lower()

    sessions_qs = ChatSession.objects.filter(
        seller=seller,
        session_type=ChatSession.TYPE_DIRECT,
        is_archived_by_seller=False
    ).order_by("-updated_at")

    if tab == "belum_dibaca":
        sessions_qs = sessions_qs.filter(
            messages__sender_type=ChatMessage.SENDER_BUYER,
            messages__is_read=False
        ).distinct()

    results = []
    for s in sessions_qs:
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
def seller_knowledge_list_create_api(request):
    """
    GET: Melihat daftar Q&A yang dimiliki penjual. Opsional filter `?product_id=...`
    
    POST: Menambahkan Q&A baru per produk.
    Payload:
    {
        "product_id": "PRD-01",
        "product_name": "Sabun Bambu",
        "question": "Apakah aman untuk anak-anak?",
        "answer": "Ya, aman karena formula alami 100%."
    }
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

        if not product_id or not question or not answer:
            return _json_error("product_id, question, dan answer wajib diisi.")

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
    GET, PUT/PATCH, DELETE: Mengelola entri Q&A individual milik penjual.
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
def seller_chat_settings_api(request):
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
def seller_knowledge_toggle_api(request, pk):
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


def submit_session_rating_api(request, session_id):
    """
    Payload: {"rating": 5, "feedback": "Penjual sangat ramah!"}
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
    Payload:
    {
        "reported_user_id": 2,
        "session_id": "<uuid-optional>",
        "reason": "Pembeli berkata kasar dan tidak sopan."
    }
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

@login_required
