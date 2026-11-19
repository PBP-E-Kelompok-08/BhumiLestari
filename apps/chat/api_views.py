import logging
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    BroadcastChannel,
    BroadcastMessage,
    ChatMessage,
    ChatSession,
    ProductKnowledge,
    SessionProductContext,
    SessionRating,
    UserReport,
)
from .permissions import IsSessionParticipantOrStaff
from .serializers import (
    AISessionCreateSerializer,
    BroadcastChannelSerializer,
    BroadcastMessageSerializer,
    ChatMessageSerializer,
    MessageContentSerializer,
    ProductContextAddSerializer,
    ProductKnowledgeSerializer,
    SellerChatSettingsSerializer,
    SessionProductContextSerializer,
    SessionRatingSerializer,
    UserReportCreateSerializer,
)
from .services.ai_service import (
    build_system_prompt,
    parse_handover_signal,
    query_openrouter,
)
from .views import (
    _ensure_all_sellers_have_broadcast_channels,
    _get_seller_chat_settings,
    _get_seller_store_name,
    _is_store_open,
    _transfer_to_ai_session,
    _transfer_to_direct_session,
)


logger = logging.getLogger(__name__)
User = get_user_model()


def _error_response(message, status_code=status.HTTP_400_BAD_REQUEST):
    return Response(
        {
            "status": "error",
            "message": message,
            "detail": message,
        },
        status=status_code,
    )


class SearchSellersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()

        sellers_qs = (
            User.objects.filter(
                Q(role="seller") | Q(seller_profile__isnull=False)
            )
            .distinct()
            .exclude(id=request.user.id)
        )

        if q:
            sellers_qs = sellers_qs.filter(
                Q(seller_profile__store_name__icontains=q)
                | Q(full_name__icontains=q)
                | Q(email__icontains=q)
                | Q(username__icontains=q)
            ).distinct()[:15]
        else:
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

            results.append(
                {
                    "id": s.id,
                    "store_name": store_name,
                    "email": s.email,
                    "initial": initial,
                }
            )

        return Response(
            {
                "status": "success",
                "total": len(results),
                "sellers": results,
            }
        )


class AISessionCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AISessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        seller_id = serializer.validated_data["seller_id"]
        products = serializer.validated_data.get("products", [])

        seller = get_object_or_404(User, id=seller_id)
        buyer = request.user

        if buyer == seller:
            return _error_response(
                "Penjual tidak dapat membuka sesi tanya produk ke diri sendiri.",
                status.HTTP_400_BAD_REQUEST,
            )

        chat_settings = _get_seller_chat_settings(seller)
        is_new = False

        target_session = ChatSession.objects.filter(
            buyer=buyer,
            seller=seller,
            session_type=ChatSession.TYPE_AI,
            status=ChatSession.STATUS_ACTIVE,
        ).first()

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
                target_session = ChatSession.objects.create(
                    buyer=buyer,
                    seller=seller,
                    session_type=ChatSession.TYPE_AI,
                    status=ChatSession.STATUS_ACTIVE,
                )
                is_new = True

        if (
            is_new
            and chat_settings.is_auto_reply_enabled
            and chat_settings.welcome_message
        ):
            ChatMessage.objects.create(
                session=target_session,
                sender=None,
                sender_type=ChatMessage.SENDER_AI,
                content=f"{chat_settings.welcome_message}\n\n-{chat_settings.bot_name}",
            )

        for p in products:
            p_id = str(p.get("product_id", "")).strip()
            p_name = str(p.get("product_name", "")).strip()
            if p_id:
                SessionProductContext.objects.get_or_create(
                    session=target_session,
                    product_id=p_id,
                    defaults={"product_name": p_name},
                )

        target_session.is_archived_by_buyer = False
        target_session.updated_at = timezone.now()
        target_session.save(
            update_fields=["is_archived_by_buyer", "updated_at"]
        )

        contexts = SessionProductContextSerializer(
            target_session.product_contexts.all(),
            many=True,
        ).data

        return Response(
            {
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
            }
        )


class SessionProductContextAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_session(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user not in (session.buyer, session.seller):
            return None
        return session

    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        if session is None:
            return _error_response("Akses ditolak.", status.HTTP_403_FORBIDDEN)

        serializer = ProductContextAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        products = serializer.validated_data.get("products", [])

        added = []
        for p in products:
            p_id = str(p.get("product_id", "")).strip()
            p_name = str(p.get("product_name", "")).strip()
            if p_id:
                ctx, created = SessionProductContext.objects.get_or_create(
                    session=session,
                    product_id=p_id,
                    defaults={"product_name": p_name},
                )
                if created:
                    added.append(
                        {
                            "product_id": ctx.product_id,
                            "product_name": ctx.product_name,
                        }
                    )

        all_contexts = SessionProductContextSerializer(
            session.product_contexts.all(),
            many=True,
        ).data
        return Response(
            {
                "status": "success",
                "added": added,
                "all_product_contexts": all_contexts,
            }
        )

    def delete(self, request, session_id):
        session = self.get_session(request, session_id)
        if session is None:
            return _error_response("Akses ditolak.", status.HTTP_403_FORBIDDEN)

        product_id = request.query_params.get("product_id") or request.data.get(
            "product_id"
        )
        if product_id and product_id != "all":
            deleted_count, _ = session.product_contexts.filter(
                product_id=product_id
            ).delete()
            message = f"Konteks produk {product_id} berhasil dihapus."
        else:
            deleted_count, _ = session.product_contexts.all().delete()
            message = "Semua konteks produk berhasil dihapus."

        all_contexts = SessionProductContextSerializer(
            session.product_contexts.all(),
            many=True,
        ).data
        return Response(
            {
                "status": "success",
                "message": message,
                "deleted_count": deleted_count,
                "all_product_contexts": all_contexts,
            }
        )


class DeleteProductContextAPIView(SessionProductContextAPIView):
    def post(self, request, session_id):
        return self.delete(request, session_id)


class SendAIMessageAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user != session.buyer:
            return _error_response(
                "Hanya pembeli di sesi ini yang dapat mengirim pesan ke AI.",
                status.HTTP_403_FORBIDDEN,
            )

        if session.session_type != ChatSession.TYPE_AI:
            return _error_response(
                "Sesi ini bukan sesi AI. Gunakan endpoint direct-send.",
                status.HTTP_400_BAD_REQUEST,
            )

        if session.status != ChatSession.STATUS_ACTIVE:
            return _error_response(
                "Sesi AI ini sudah selesai dan tidak dapat menerima pesan baru.",
                status.HTTP_400_BAD_REQUEST,
            )

        serializer = MessageContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data["content"]

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

        if not chat_settings.is_auto_reply_enabled:
            direct_session = _transfer_to_direct_session(
                session,
                reason=ChatSession.HANDOVER_BOT_DISABLED,
                forward_question=content,
            )
            return Response(
                {
                    "status": "success",
                    "handover": True,
                    "direct_session_id": str(direct_session.id),
                    "reply": "Bot otomatis toko sedang dinonaktifkan. Pertanyaan Anda telah diteruskan ke penjual.",
                }
            )

        if not _is_store_open(chat_settings):
            closed_reply = f"{chat_settings.closed_message}\n\n-{bot_name}"
            ai_msg = ChatMessage.objects.create(
                session=session,
                sender=None,
                sender_type=ChatMessage.SENDER_AI,
                content=closed_reply,
            )
            session.save(update_fields=["updated_at"])
            return Response(
                {
                    "status": "success",
                    "handover": False,
                    "reply": closed_reply,
                    "is_closed": True,
                    "message_id": str(ai_msg.id),
                    "session_id": str(session.id),
                }
            )

        product_contexts = list(session.product_contexts.all())
        all_product_qas = (
            ProductKnowledge.objects.filter(
                seller=session.seller,
                is_active=True,
            )
            .exclude(product_id__isnull=True)
            .exclude(product_id="")
        )

        knowledges_by_product = {}
        for k in all_product_qas:
            knowledges_by_product.setdefault(k.product_id, []).append(k)

        general_knowledges = list(
            ProductKnowledge.objects.filter(
                Q(product_id__isnull=True) | Q(product_id=""),
                seller=session.seller,
                is_active=True,
            )
        )

        real_products = []
        try:
            from apps.products.models import Product

            real_products = list(
                Product.objects.filter(seller__user=session.seller).exclude(
                    status__in=["rejected", "expired"]
                )[:15]
            )
        except Exception as e:
            logger.warning(
                "Gagal mengambil katalog produk penjual untuk AI prompt: %s",
                e,
            )

        system_prompt = build_system_prompt(
            store_name,
            product_contexts,
            knowledges_by_product,
            bot_name=bot_name,
            general_knowledges=general_knowledges,
            real_products=real_products,
        )

        recent_msgs = session.messages.exclude(id=user_msg.id).order_by(
            "-created_at"
        )[:8]
        recent_msgs = reversed(recent_msgs)

        messages_payload = [{"role": "system", "content": system_prompt}]
        for m in recent_msgs:
            role = (
                "user"
                if m.sender_type == ChatMessage.SENDER_BUYER
                else "assistant"
            )
            messages_payload.append({"role": role, "content": m.content})
        messages_payload.append({"role": "user", "content": content})

        try:
            raw_ai_reply = query_openrouter(messages_payload)
        except Exception as e:
            logger.error("Gagal memanggil AI service: %s", e)
            direct_session = _transfer_to_direct_session(
                session,
                reason=ChatSession.HANDOVER_UNANSWERED,
                forward_question=content,
            )
            return Response(
                {
                    "status": "success",
                    "handover": True,
                    "direct_session_id": str(direct_session.id),
                    "reply": "Layanan AI asisten sedang sibuk. Pertanyaan Anda telah otomatis kami teruskan ke ruang obrolan langsung dengan penjual.",
                }
            )

        is_handover, cleaned_reply = parse_handover_signal(raw_ai_reply)

        if is_handover:
            direct_session = _transfer_to_direct_session(
                session,
                reason=ChatSession.HANDOVER_UNANSWERED,
                forward_question=content,
            )
            return Response(
                {
                    "status": "success",
                    "handover": True,
                    "direct_session_id": str(direct_session.id),
                    "reply": cleaned_reply,
                    "message": "Jawaban tidak ada di daftar penjual. Sesi dialihkan ke chat langsung dengan penjual.",
                }
            )

        ai_msg = ChatMessage.objects.create(
            session=session,
            sender=None,
            sender_type=ChatMessage.SENDER_AI,
            content=cleaned_reply,
        )
        session.save(update_fields=["updated_at"])

        return Response(
            {
                "status": "success",
                "handover": False,
                "reply": cleaned_reply,
                "message_id": str(ai_msg.id),
                "session_id": str(session.id),
            }
        )


class EscalateToSellerAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user != session.buyer:
            return _error_response(
                "Hanya pembeli di sesi ini yang dapat beralih ke penjual.",
                status.HTTP_403_FORBIDDEN,
            )

        if session.session_type != ChatSession.TYPE_AI:
            return _error_response(
                "Sesi ini sudah bukan sesi AI.",
                status.HTTP_400_BAD_REQUEST,
            )

        if session.status != ChatSession.STATUS_ACTIVE:
            return _error_response(
                "Sesi AI ini sudah selesai dan tidak dapat dialihkan lagi.",
                status.HTTP_400_BAD_REQUEST,
            )

        direct_session = _transfer_to_direct_session(
            session,
            reason=ChatSession.HANDOVER_MANUAL,
        )

        return Response(
            {
                "status": "success",
                "handover": True,
                "direct_session_id": str(direct_session.id),
                "message": "Sesi chat baru langsung dengan penjual berhasil dibuat.",
            }
        )


class SwitchToAISessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user != session.buyer:
            return _error_response(
                "Akses ditolak. Hanya pembeli yang dapat beralih ke asisten AI.",
                status.HTTP_403_FORBIDDEN,
            )

        if session.session_type != ChatSession.TYPE_DIRECT:
            return _error_response(
                "Sesi ini sudah merupakan sesi asisten AI.",
                status.HTTP_400_BAD_REQUEST,
            )

        if session.status != ChatSession.STATUS_ACTIVE:
            return _error_response(
                "Sesi obrolan langsung ini sudah selesai.",
                status.HTTP_400_BAD_REQUEST,
            )

        ai_session = _transfer_to_ai_session(session)
        chat_settings = _get_seller_chat_settings(session.seller)
        bot_name = (
            chat_settings.bot_name
            if (chat_settings and chat_settings.bot_name)
            else "Asisten Toko"
        )

        return Response(
            {
                "status": "success",
                "message": f"Berhasil beralih kembali ke Asisten AI ({bot_name}).",
                "ai_session_id": str(ai_session.id),
                "session_type": ai_session.session_type,
            }
        )


class SessionMessagesAPIView(APIView):
    permission_classes = [IsAuthenticated, IsSessionParticipantOrStaff]

    def get(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        self.check_object_permissions(request, session)

        if request.user == session.buyer:
            session.messages.exclude(
                sender_type=ChatMessage.SENDER_BUYER
            ).filter(is_read=False).update(is_read=True)
        elif request.user == session.seller:
            session.messages.filter(
                sender_type=ChatMessage.SENDER_BUYER,
                is_read=False,
            ).update(is_read=True)

        messages_qs = session.messages.select_related("sender").order_by(
            "created_at"
        )
        messages_data = ChatMessageSerializer(messages_qs, many=True).data
        contexts = SessionProductContextSerializer(
            session.product_contexts.all(),
            many=True,
        ).data

        rating_data = None
        if hasattr(session, "rating"):
            rating_data = SessionRatingSerializer(session.rating).data

        return Response(
            {
                "status": "success",
                "session": {
                    "id": str(session.id),
                    "session_type": session.session_type,
                    "status": session.status,
                    "handover_reason": session.handover_reason,
                    "origin_session_id": (
                        str(session.origin_session_id)
                        if session.origin_session_id
                        else None
                    ),
                    "is_archived_by_buyer": session.is_archived_by_buyer,
                    "is_archived_by_seller": session.is_archived_by_seller,
                    "buyer": {
                        "id": session.buyer.id,
                        "email": session.buyer.email,
                        "name": session.buyer.full_name,
                    },
                    "seller": {
                        "id": session.seller.id,
                        "email": session.seller.email,
                        "store_name": _get_seller_store_name(session.seller),
                    },
                    "product_contexts": contexts,
                    "rating": rating_data,
                },
                "messages": messages_data,
            }
        )


class SendDirectMessageAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user not in (session.buyer, session.seller):
            return _error_response("Akses ditolak.", status.HTTP_403_FORBIDDEN)

        if session.session_type != ChatSession.TYPE_DIRECT:
            return _error_response(
                "Endpoint ini hanya untuk sesi obrolan langsung (direct).",
                status.HTTP_400_BAD_REQUEST,
            )

        if session.status != ChatSession.STATUS_ACTIVE:
            return _error_response(
                "Sesi obrolan ini sudah selesai dan tidak dapat menerima pesan baru.",
                status.HTTP_400_BAD_REQUEST,
            )

        serializer = MessageContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data["content"]

        sender_type = (
            ChatMessage.SENDER_BUYER
            if request.user == session.buyer
            else ChatMessage.SENDER_SELLER
        )

        msg = ChatMessage.objects.create(
            session=session,
            sender=request.user,
            sender_type=sender_type,
            content=content,
            is_inherited_from_ai=False,
            is_read=False,
        )

        session.save(update_fields=["updated_at"])

        return Response(
            {
                "status": "success",
                "message": ChatMessageSerializer(msg).data,
            }
        )


class ToggleArchiveSessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user == session.buyer:
            session.is_archived_by_buyer = not session.is_archived_by_buyer
            session.save(update_fields=["is_archived_by_buyer"])
            return Response(
                {
                    "status": "success",
                    "is_archived": session.is_archived_by_buyer,
                }
            )
        if request.user == session.seller:
            session.is_archived_by_seller = not session.is_archived_by_seller
            session.save(update_fields=["is_archived_by_seller"])
            return Response(
                {
                    "status": "success",
                    "is_archived": session.is_archived_by_seller,
                }
            )

        return _error_response("Akses ditolak.", status.HTTP_403_FORBIDDEN)


class BuyerInboxSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        buyer = request.user
        tab = (request.query_params.get("tab") or "semua").lower()
        search = (request.query_params.get("search") or "").strip().lower()

        sessions_qs = (
            ChatSession.objects.filter(buyer=buyer)
            .exclude(status=ChatSession.STATUS_RESOLVED)
            .select_related("seller")
            .prefetch_related("product_contexts")
            .order_by("-updated_at")
        )

        if tab == "diarsipkan":
            sessions_qs = sessions_qs.filter(is_archived_by_buyer=True)
        else:
            sessions_qs = sessions_qs.filter(is_archived_by_buyer=False)
            if tab == "belum_dibaca":
                sessions_qs = sessions_qs.filter(
                    messages__sender_type__in=[
                        ChatMessage.SENDER_SELLER,
                        ChatMessage.SENDER_AI,
                    ],
                    messages__is_read=False,
                ).distinct()

        seen_seller_ids = set()
        results = []
        for s in sessions_qs:
            if s.seller_id in seen_seller_ids:
                continue
            seen_seller_ids.add(s.seller_id)

            last_msg = s.messages.order_by("-created_at").first()
            store_name = _get_seller_store_name(s.seller)

            if search:
                match_store = (
                    search in store_name.lower()
                    or search in s.seller.email.lower()
                )
                match_msg = last_msg and search in last_msg.content.lower()
                if not (match_store or match_msg):
                    continue

            unread_count = s.messages.filter(
                sender_type__in=[
                    ChatMessage.SENDER_SELLER,
                    ChatMessage.SENDER_AI,
                ],
                is_read=False,
            ).count()
            contexts = SessionProductContextSerializer(
                s.product_contexts.all(),
                many=True,
            ).data

            results.append(
                {
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
                    "last_message": (
                        {
                            "content": last_msg.content,
                            "sender_type": last_msg.sender_type,
                            "created_at": last_msg.created_at.isoformat(),
                        }
                        if last_msg
                        else None
                    ),
                    "updated_at": s.updated_at.isoformat(),
                }
            )

        return Response(
            {
                "status": "success",
                "tab": tab,
                "total_sessions": len(results),
                "sessions": results,
            }
        )


class SellerInboxSessionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        seller = request.user
        tab = (request.query_params.get("tab") or "semua").lower()
        search = (request.query_params.get("search") or "").strip().lower()

        sessions_qs = (
            ChatSession.objects.filter(
                seller=seller,
                session_type=ChatSession.TYPE_DIRECT,
                status=ChatSession.STATUS_ACTIVE,
            )
            .select_related("buyer")
            .prefetch_related("product_contexts")
            .order_by("-updated_at")
        )

        if tab == "diarsipkan":
            sessions_qs = sessions_qs.filter(is_archived_by_seller=True)
        else:
            sessions_qs = sessions_qs.filter(is_archived_by_seller=False)
            if tab == "belum_dibaca":
                sessions_qs = sessions_qs.filter(
                    messages__sender_type=ChatMessage.SENDER_BUYER,
                    messages__is_read=False,
                ).distinct()

        seen_buyer_ids = set()
        results = []
        for s in sessions_qs:
            if s.buyer_id in seen_buyer_ids:
                continue
            seen_buyer_ids.add(s.buyer_id)

            last_msg = s.messages.order_by("-created_at").first()

            if tab == "belum_dibalas":
                if (
                    not last_msg
                    or last_msg.sender_type != ChatMessage.SENDER_BUYER
                ):
                    continue

            buyer_name = s.buyer.full_name or s.buyer.email.split("@")[0]
            if search:
                match_buyer = (
                    search in buyer_name.lower()
                    or search in s.buyer.email.lower()
                )
                match_msg = last_msg and search in last_msg.content.lower()
                if not (match_buyer or match_msg):
                    continue

            unread_count = s.messages.filter(
                sender_type=ChatMessage.SENDER_BUYER,
                is_read=False,
            ).count()
            contexts = SessionProductContextSerializer(
                s.product_contexts.all(),
                many=True,
            ).data

            results.append(
                {
                    "id": str(s.id),
                    "status": s.status,
                    "buyer": {
                        "id": s.buyer.id,
                        "email": s.buyer.email,
                        "name": buyer_name,
                    },
                    "unread_count": unread_count,
                    "is_archived": s.is_archived_by_seller,
                    "product_contexts": contexts,
                    "last_message": (
                        {
                            "content": last_msg.content,
                            "sender_type": last_msg.sender_type,
                            "created_at": last_msg.created_at.isoformat(),
                        }
                        if last_msg
                        else None
                    ),
                    "updated_at": s.updated_at.isoformat(),
                }
            )

        return Response(
            {
                "status": "success",
                "tab": tab,
                "total_sessions": len(results),
                "sessions": results,
            }
        )


class SellerChatSettingsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings_obj = _get_seller_chat_settings(request.user)
        serializer = SellerChatSettingsSerializer(settings_obj)
        return Response(
            {
                "status": "success",
                "settings": serializer.data,
            }
        )

    def _update(self, request):
        settings_obj = _get_seller_chat_settings(request.user)
        serializer = SellerChatSettingsSerializer(
            settings_obj,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.save()
        return Response(
            {
                "status": "success",
                "message": "Pengaturan bot berhasil disimpan.",
                "settings": SellerChatSettingsSerializer(settings_obj).data,
            }
        )

    def post(self, request):
        return self._update(request)

    def put(self, request):
        return self._update(request)

    def patch(self, request):
        return self._update(request)


class SellerKnowledgeListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ProductKnowledge.objects.filter(seller=request.user)
        product_id = request.query_params.get("product_id")
        if product_id:
            qs = qs.filter(product_id=product_id)

        serializer = ProductKnowledgeSerializer(qs, many=True)
        return Response(
            {
                "status": "success",
                "total": len(serializer.data),
                "knowledges": serializer.data,
            }
        )

    def post(self, request):
        serializer = ProductKnowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(seller=request.user)
        return Response(
            {
                "status": "success",
                "message": "Knowledge Q&A berhasil ditambahkan.",
                "knowledge": ProductKnowledgeSerializer(item).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SellerKnowledgeDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        return get_object_or_404(ProductKnowledge, id=pk, seller=request.user)

    def get(self, request, pk):
        item = self.get_object(request, pk)
        return Response(
            {
                "status": "success",
                "knowledge": ProductKnowledgeSerializer(item).data,
            }
        )

    def _update(self, request, pk):
        item = self.get_object(request, pk)
        serializer = ProductKnowledgeSerializer(
            item,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(
            {
                "status": "success",
                "message": "Knowledge Q&A berhasil diperbarui.",
                "knowledge": ProductKnowledgeSerializer(item).data,
            }
        )

    def put(self, request, pk):
        return self._update(request, pk)

    def patch(self, request, pk):
        return self._update(request, pk)

    def delete(self, request, pk):
        item = self.get_object(request, pk)
        item.delete()
        return Response(
            {
                "status": "success",
                "message": "Knowledge Q&A berhasil dihapus.",
            }
        )


class SellerKnowledgeToggleAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        item = get_object_or_404(ProductKnowledge, id=pk, seller=request.user)
        item.is_active = not item.is_active
        item.save(update_fields=["is_active"])
        return Response(
            {
                "status": "success",
                "id": item.id,
                "is_active": item.is_active,
                "message": (
                    f"Kata kunci '{item.question}' sekarang "
                    f"{'aktif' if item.is_active else 'nonaktif'}."
                ),
            }
        )


class SessionRatingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        session = get_object_or_404(ChatSession, id=session_id)
        if request.user != session.buyer:
            return _error_response(
                "Hanya pembeli yang dapat memberikan rating percakapan.",
                status.HTTP_403_FORBIDDEN,
            )

        serializer = SessionRatingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rating_val = serializer.validated_data.get("rating", 5)
        feedback_val = (
            serializer.validated_data.get("feedback") or ""
        ).strip()

        rating_obj, _ = SessionRating.objects.update_or_create(
            session=session,
            defaults={
                "user": request.user,
                "rating": rating_val,
                "feedback": feedback_val,
            },
        )

        return Response(
            {
                "status": "success",
                "message": "Terima kasih atas rating dan feedback Anda!",
                "rating": {
                    "session_id": str(session.id),
                    "rating": rating_obj.rating,
                    "feedback": rating_obj.feedback,
                    "created_at": rating_obj.created_at.isoformat(),
                },
            }
        )


class UserReportCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UserReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reported_user_id = serializer.validated_data["reported_user_id"]
        reason = serializer.validated_data["reason"]
        session_id = serializer.validated_data.get("session_id")

        reported_user = get_object_or_404(User, id=reported_user_id)
        if reported_user == request.user:
            return _error_response(
                "Anda tidak dapat melaporkan diri sendiri.",
                status.HTTP_400_BAD_REQUEST,
            )

        session = None
        if session_id:
            session = ChatSession.objects.filter(id=session_id).first()

        report = UserReport.objects.create(
            reporter=request.user,
            reported_user=reported_user,
            session=session,
            reason=reason,
        )

        return Response(
            {
                "status": "success",
                "message": "Laporan Anda telah berhasil dikirimkan.",
                "report_id": report.id,
            },
            status=status.HTTP_201_CREATED,
        )


class BroadcastChannelListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tab = (request.query_params.get("tab") or "semua").lower()
        search = (request.query_params.get("search") or "").strip().lower()

        _ensure_all_sellers_have_broadcast_channels()

        channels_qs = BroadcastChannel.objects.select_related(
            "seller"
        ).order_by("-followers_count")

        user_channels_filter = Q(followers=request.user) | Q(
            added_by=request.user
        )
        if getattr(request.user, "role", "") == "seller":
            user_channels_filter |= Q(seller=request.user)
        channels_qs = channels_qs.filter(user_channels_filter).distinct()

        if tab == "diarsipkan":
            channels_qs = channels_qs.filter(archived_by=request.user)
        else:
            channels_qs = channels_qs.exclude(archived_by=request.user)

        channels_list = list(channels_qs)
        if getattr(request.user, "role", "") == "seller":
            channels_list.sort(
                key=lambda c: 0 if c.seller_id == request.user.id else 1
            )

        results = []
        my_channel = None
        other_channels = []

        for c in channels_list:
            last_msg = c.messages.first() if c.messages.exists() else None
            if search:
                name_match = (
                    search in c.name.lower() or search in c.description.lower()
                )
                msg_match = last_msg and search in last_msg.content.lower()
                if not (name_match or msg_match):
                    continue

            item_data = BroadcastChannelSerializer(
                c,
                context={"request": request},
            ).data
            results.append(item_data)
            if item_data["is_owner"]:
                my_channel = item_data
            else:
                other_channels.append(item_data)

        return Response(
            {
                "status": "success",
                "tab": tab,
                "total": len(results),
                "my_channel": my_channel,
                "other_channels": other_channels,
                "channels": results,
            }
        )


class ToggleArchiveBroadcastChannelAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        channel = get_object_or_404(BroadcastChannel, id=channel_id)
        if channel.archived_by.filter(id=request.user.id).exists():
            channel.archived_by.remove(request.user)
            is_archived = False
        else:
            channel.archived_by.add(request.user)
            is_archived = True

        return Response(
            {
                "status": "success",
                "channel_id": channel.id,
                "is_archived": is_archived,
                "message": (
                    f"Channel {'diarsipkan' if is_archived else 'dikeluarkan dari arsip'}."
                ),
            }
        )


class ToggleFollowBroadcastChannelAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        channel = get_object_or_404(BroadcastChannel, id=channel_id)
        if channel.seller == request.user:
            return _error_response(
                "Anda tidak dapat mengikuti channel Anda sendiri.",
                status.HTTP_400_BAD_REQUEST,
            )

        if channel.followers.filter(id=request.user.id).exists():
            channel.followers.remove(request.user)
            is_following = False
        else:
            channel.followers.add(request.user)
            is_following = True

        channel.followers_count = channel.followers.count()
        channel.save(update_fields=["followers_count"])

        return Response(
            {
                "status": "success",
                "channel_id": channel.id,
                "is_following": is_following,
                "followers_count": channel.followers_count,
                "message": (
                    f"Berhasil {'mengikuti' if is_following else 'berhenti mengikuti'} "
                    f"{channel.name}."
                ),
            }
        )


class ExploreBroadcastChannelsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _ensure_all_sellers_have_broadcast_channels()
        q = (request.query_params.get("q") or "").strip()

        channels_qs = BroadcastChannel.objects.select_related(
            "seller"
        ).exclude(seller=request.user)
        if q:
            channels_qs = channels_qs.filter(
                Q(name__icontains=q)
                | Q(description__icontains=q)
                | Q(seller__full_name__icontains=q)
                | Q(seller__seller_profile__store_name__icontains=q)
            ).distinct()[:15]
        else:
            channels_qs = channels_qs.order_by("-followers_count")[:15]

        results = []
        for c in channels_qs:
            data = BroadcastChannelSerializer(
                c,
                context={"request": request},
            ).data
            results.append(
                {
                    "id": data["id"],
                    "name": data["name"],
                    "store_name": data["store_name"],
                    "description": data["description"],
                    "followers_count": data["followers_count"],
                    "is_following": data["is_following"],
                    "is_added": data["is_added"],
                }
            )

        return Response(
            {
                "status": "success",
                "total": len(results),
                "channels": results,
            }
        )


class AddBroadcastChannelAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, channel_id):
        channel = get_object_or_404(BroadcastChannel, id=channel_id)
        if channel.seller == request.user:
            return _error_response(
                "Ini adalah saluran toko Anda sendiri.",
                status.HTTP_400_BAD_REQUEST,
            )

        channel.added_by.add(request.user)
        serialized = BroadcastChannelSerializer(
            channel,
            context={"request": request},
        ).data

        return Response(
            {
                "status": "success",
                "channel": {
                    "id": serialized["id"],
                    "name": serialized["name"],
                    "description": serialized["description"],
                    "followers_count": serialized["followers_count"],
                    "is_owner": False,
                    "is_following": serialized["is_following"],
                    "is_archived": serialized["is_archived"],
                },
                "message": (
                    f"Saluran {channel.name} berhasil ditambahkan ke daftar channel Anda."
                ),
            }
        )


class BroadcastMessagesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, channel_id):
        channel = get_object_or_404(BroadcastChannel, id=channel_id)
        messages_qs = channel.messages.all()

        if request.user != channel.seller:
            messages_qs.update(viewed_count=F("viewed_count") + 1)

        messages = BroadcastMessageSerializer(
            channel.messages.all(),
            many=True,
        ).data
        serialized_channel = BroadcastChannelSerializer(
            channel,
            context={"request": request},
        ).data

        return Response(
            {
                "status": "success",
                "channel": {
                    "id": serialized_channel["id"],
                    "name": serialized_channel["name"],
                    "followers_count": serialized_channel["followers_count"],
                    "is_owner": serialized_channel["is_owner"],
                    "is_archived": serialized_channel["is_archived"],
                    "is_following": serialized_channel["is_following"],
                },
                "messages": messages,
            }
        )

    def post(self, request, channel_id):
        channel = get_object_or_404(BroadcastChannel, id=channel_id)
        if request.user != channel.seller:
            return _error_response(
                "Anda tidak memiliki akses untuk mengirim pesan pada channel ini.",
                status.HTTP_403_FORBIDDEN,
            )

        serializer = MessageContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data["content"]

        b_msg = BroadcastMessage.objects.create(
            channel=channel,
            content=content,
            viewed_count=0,
        )

        return Response(
            {
                "status": "success",
                "message": BroadcastMessageSerializer(b_msg).data,
            },
            status=status.HTTP_201_CREATED,
        )


class SendBroadcastMessageAPIView(BroadcastMessagesAPIView):
    pass
