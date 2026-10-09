import json
import logging
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model

from apps.chat.models import ProductKnowledge, ChatSession, SessionProductContext, ChatMessage
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
    """
    Fungsi utilitas untuk membuat sesi baru bertipe 'direct' dengan penjual:
    1. Membuat ChatSession baru bertipe 'direct' dengan origin_session=ai_session.
    2. Menyalin semua SessionProductContext dari ai_session ke sesi baru.
    3. Menyalin seluruh pesan riwayat AI ke sesi baru (ditandai is_inherited_from_ai=True).
    4. Menyisipkan pesan sistem pembatas.
    5. Menambahkan pertanyaan pembeli ke sesi baru jika handover otomatis (forward_question).
    6. Mengubah status ai_session menjadi resolved/handover.
    """
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

@login_required
def get_or_create_ai_session_api(request):
    """
    POST: Inisiasi sesi chat AI untuk satu atau lebih produk.
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
    POST: Menambahkan konteks produk ke sesi yang sedang berjalan.
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
    """
    POST: Pembeli mengirim pertanyaan ke AI.
    """
    if request.method != "POST":
        return _json_error("Hanya metode POST yang diizinkan.", status=405)

    session = get_object_or_404(ChatSession, id=session_id)
    if request.user != session.buyer:
        return _json_error("Hanya pembeli di sesi ini yang dapat mengirim pesan ke AI.", status=403)

    if session.session_type != ChatSession.TYPE_AI:
        return _json_error("Sesi ini bukan sesi AI.", status=400)

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
        return _json_error("Layanan AI asisten sedang sibuk.", status=503)

    is_handover, cleaned_reply = parse_handover_signal(raw_ai_reply)

    if not is_handover:
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


@login_required
def escalate_to_seller_api(request, session_id):
    """
    POST: Pembeli secara manual mengklik tombol 'Chat dengan Penjual' di dalam chat AI.
    """
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


@login_required
def get_session_messages_api(request, session_id):
    """
    GET: Mengambil seluruh riwayat pesan suatu sesi.
    """
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
