# AI DISCLOSURE: Test ini dibuat oleh AI untuk mempermudah memastikan apakah backendnya berjalan dgn baik atau tidak

import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

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
    parse_handover_signal,
    query_openrouter,
    HANDOVER_TOKEN,
)

User = get_user_model()


class ChatModelTest(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="buyer@example.com",
            username="buyer1",
            password="password123",
            role=User.ROLE_BUYER,
        )
        self.seller = User.objects.create_user(
            email="seller@example.com",
            username="seller1",
            password="password123",
            role=User.ROLE_SELLER,
        )

    def test_create_models(self):
        # 1. Product Knowledge
        pk = ProductKnowledge.objects.create(
            seller=self.seller,
            product_id="PRD-01",
            product_name="Sabun Batang Bambu",
            question="Apakah alami?",
            answer="Ya, 100% bahan alami.",
        )
        self.assertIn("Sabun Batang Bambu", str(pk))

        # 2. Chat Session
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        self.assertEqual(session.status, ChatSession.STATUS_ACTIVE)
        self.assertIn("AI", str(session))

        # 3. Product Context
        ctx = SessionProductContext.objects.create(
            session=session,
            product_id="PRD-01",
            product_name="Sabun Batang Bambu",
        )
        self.assertEqual(session.product_contexts.count(), 1)
        self.assertIn("Sabun Batang Bambu", str(ctx))

        # 4. Chat Message
        msg = ChatMessage.objects.create(
            session=session,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Halo, apakah produk ini ready?",
        )
        self.assertFalse(msg.is_inherited_from_ai)
        self.assertIn("ready?", str(msg))


class AIServiceTest(TestCase):
    def test_build_system_prompt_multi_product(self):
        ctx1 = MagicMock(product_id="P1", product_name="Produk A")
        ctx2 = MagicMock(product_id="P2", product_name="Produk B")

        qa1 = MagicMock(question="Bahan apa?", answer="Kayu jati.")
        qa2 = MagicMock(question="Bisa COD?", answer="Bisa.")

        knowledges_by_product = {
            "P1": [qa1],
            "P2": [qa2],
        }

        prompt = build_system_prompt("Toko Lestari", [ctx1, ctx2], knowledges_by_product)
        self.assertIn("Toko Lestari", prompt)
        self.assertIn("Produk A", prompt)
        self.assertIn("Produk B", prompt)
        self.assertIn("Kayu jati.", prompt)
        self.assertIn("Bisa.", prompt)
        self.assertIn(HANDOVER_TOKEN, prompt)

    def test_parse_handover_signal(self):
        text_normal = "Produk ini terbuat dari serat kelapa alami."
        is_handover, clean_text = parse_handover_signal(text_normal)
        self.assertFalse(is_handover)
        self.assertEqual(clean_text, text_normal)

        text_handover = f"{HANDOVER_TOKEN}: Maaf informasi belum ada, dialihkan ke penjual."
        is_handover, clean_text = parse_handover_signal(text_handover)
        self.assertTrue(is_handover)
        self.assertEqual(clean_text, "Maaf informasi belum ada, dialihkan ke penjual.")

    @patch("requests.post")
    def test_query_openrouter_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Jawaban dari AI"}}]
        }
        mock_post.return_value = mock_resp

        with patch.dict("os.environ", {"API_KEY": "test-key"}):
            reply = query_openrouter([{"role": "user", "content": "Halo"}])
            self.assertEqual(reply, "Jawaban dari AI")


class ChatAPITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.buyer = User.objects.create_user(
            email="buyer@test.com",
            username="buyer_test",
            password="password123",
            role=User.ROLE_BUYER,
            full_name="Pembeli Satu",
        )
        self.seller = User.objects.create_user(
            email="seller@test.com",
            username="seller_test",
            password="password123",
            role=User.ROLE_SELLER,
            full_name="Penjual Dua",
        )
        self.other_user = User.objects.create_user(
            email="other@test.com",
            username="other_test",
            password="password123",
            role=User.ROLE_BUYER,
        )

        # Pastikan default jam operasional toko buka selama unit testing standar
        settings_obj, _ = SellerChatSettings.objects.get_or_create(seller=self.seller)
        settings_obj.operating_hours_start = "00:00"
        settings_obj.operating_hours_end = "23:59"
        settings_obj.save()

        # Knowledge base
        ProductKnowledge.objects.create(
            seller=self.seller,
            product_id="P1",
            product_name="Sedotan Bambu",
            question="Apakah bisa dicuci ulang?",
            answer="Ya, bisa dicuci dan dipakai berulang kali.",
            is_active=True,
        )

    def test_get_or_create_ai_session_with_multi_products(self):
        self.client.login(username="buyer@test.com", password="password123")
        url = reverse("chat:get_or_create_ai_session")

        payload = {
            "seller_id": self.seller.id,
            "products": [
                {"product_id": "P1", "product_name": "Sedotan Bambu"},
                {"product_id": "P2", "product_name": "Sikat Gigi Kayu"},
            ],
        }
        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["session_type"], "ai")
        self.assertEqual(len(data["product_contexts"]), 2)

        session_id = data["session_id"]

        # Tambahkan konteks produk ketiga
        add_product_url = reverse("chat:add_product_context", args=[session_id])
        add_payload = {"products": [{"product_id": "P3", "product_name": "Kotak Makan Jerami"}]}
        add_resp = self.client.post(add_product_url, data=json.dumps(add_payload), content_type="application/json")
        self.assertEqual(add_resp.status_code, 200)
        add_data = add_resp.json()
        self.assertEqual(len(add_data["all_product_contexts"]), 3)

        # 1. Hapus konteks produk tunggal via DELETE ?product_id=P2
        del_resp = self.client.delete(f"{add_product_url}?product_id=P2")
        self.assertEqual(del_resp.status_code, 200)
        del_data = del_resp.json()
        self.assertEqual(del_data["status"], "success")
        self.assertEqual(len(del_data["all_product_contexts"]), 2)
        remaining_ids = [c["product_id"] for c in del_data["all_product_contexts"]]
        self.assertNotIn("P2", remaining_ids)
        self.assertIn("P1", remaining_ids)
        self.assertIn("P3", remaining_ids)

        # 2. Hapus konteks produk via POST /products/delete/
        delete_url = reverse("chat:delete_product_context", args=[session_id])
        del_p3_resp = self.client.post(
            delete_url,
            data=json.dumps({"product_id": "P3"}),
            content_type="application/json"
        )
        self.assertEqual(del_p3_resp.status_code, 200)
        self.assertEqual(len(del_p3_resp.json()["all_product_contexts"]), 1)

        # 3. Hapus semua konteks produk via POST /products/delete/ with {"all": True}
        del_all_resp = self.client.post(
            delete_url,
            data=json.dumps({"all": True}),
            content_type="application/json"
        )
        self.assertEqual(del_all_resp.status_code, 200)
        self.assertEqual(len(del_all_resp.json()["all_product_contexts"]), 0)
        self.assertEqual(SessionProductContext.objects.filter(session_id=session_id).count(), 0)

    @patch("apps.chat.views.query_openrouter")
    def test_send_ai_message_answered(self, mock_ai):
        mock_ai.return_value = "Ya, bisa dicuci dan dipakai berulang kali."

        self.client.login(username="buyer@test.com", password="password123")
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        SessionProductContext.objects.create(session=session, product_id="P1", product_name="Sedotan Bambu")

        url = reverse("chat:send_ai_message", args=[session.id])
        payload = {"content": "Apakah bisa dicuci?"}
        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["handover"])
        self.assertEqual(data["reply"], "Ya, bisa dicuci dan dipakai berulang kali.")
        self.assertEqual(session.messages.count(), 2)  # 1 buyer + 1 ai

    @patch("apps.chat.views.query_openrouter")
    def test_send_ai_message_triggers_handover(self, mock_ai):
        # AI mendeteksi jawaban tidak ada dan mengeluarkan tag handover
        mock_ai.return_value = f"{HANDOVER_TOKEN}: Maaf info garansi belum tersedia, saya alihkan ke penjual."

        self.client.login(username="buyer@test.com", password="password123")
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        SessionProductContext.objects.create(session=session, product_id="P1", product_name="Sedotan Bambu")
        # Pesan awal
        ChatMessage.objects.create(session=session, sender=self.buyer, sender_type=ChatMessage.SENDER_BUYER, content="Halo")
        ChatMessage.objects.create(session=session, sender=None, sender_type=ChatMessage.SENDER_AI, content="Halo ada yang bisa dibantu?")

        url = reverse("chat:send_ai_message", args=[session.id])
        payload = {"content": "Apakah ada garansi 1 tahun?"}
        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["handover"])
        self.assertIn("direct_session_id", data)

        # Verifikasi Sesi Direct Baru yang Terbentuk
        direct_session_id = data["direct_session_id"]
        direct_session = ChatSession.objects.get(id=direct_session_id)
        self.assertEqual(direct_session.session_type, ChatSession.TYPE_DIRECT)
        self.assertEqual(direct_session.origin_session, session)
        self.assertEqual(direct_session.handover_reason, ChatSession.HANDOVER_UNANSWERED)

        # Verifikasi produk context diwariskan
        self.assertEqual(direct_session.product_contexts.count(), 1)
        self.assertEqual(direct_session.product_contexts.first().product_id, "P1")

        # Verifikasi riwayat chat AI tersalin di bagian atas sesi direct
        direct_messages = list(direct_session.messages.order_by("created_at"))
        inherited_msgs = [m for m in direct_messages if m.is_inherited_from_ai]
        self.assertGreaterEqual(len(inherited_msgs), 2)  # Halo & Halo ada yang bisa dibantu

        # Verifikasi pertanyaan pembeli diteruskan ke penjual
        last_buyer_msg = direct_messages[-1]
        self.assertEqual(last_buyer_msg.sender_type, ChatMessage.SENDER_BUYER)
        self.assertEqual(last_buyer_msg.content, "Apakah ada garansi 1 tahun?")

    def test_manual_escalate_to_seller(self):
        self.client.login(username="buyer@test.com", password="password123")
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        SessionProductContext.objects.create(session=session, product_id="P1", product_name="Sedotan Bambu")
        ChatMessage.objects.create(session=session, sender=self.buyer, sender_type=ChatMessage.SENDER_BUYER, content="Tanya produk")

        url = reverse("chat:escalate_to_seller", args=[session.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["handover"])

        direct_session = ChatSession.objects.get(id=data["direct_session_id"])
        self.assertEqual(direct_session.session_type, ChatSession.TYPE_DIRECT)
        self.assertEqual(direct_session.handover_reason, ChatSession.HANDOVER_MANUAL)
        self.assertTrue(direct_session.messages.filter(is_inherited_from_ai=True).exists())

    def test_direct_chat_messaging_and_seller_inbox(self):
        direct_session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
        )
        SessionProductContext.objects.create(session=direct_session, product_id="P1", product_name="Sedotan Bambu")

        # 1. Pembeli kirim pesan langsung
        self.client.login(username="buyer@test.com", password="password123")
        send_url = reverse("chat:send_direct_message", args=[direct_session.id])
        resp_b = self.client.post(send_url, data=json.dumps({"content": "Halo penjual, bisa kirim hari ini?"}), content_type="application/json")
        self.assertEqual(resp_b.status_code, 200)

        # 2. Penjual balas pesan
        self.client.login(username="seller@test.com", password="password123")
        resp_s = self.client.post(send_url, data=json.dumps({"content": "Bisa kak, siap kirim."}), content_type="application/json")
        self.assertEqual(resp_s.status_code, 200)

        # 3. Penjual lihat inbox
        inbox_url = reverse("chat:seller_inbox_sessions")
        resp_inbox = self.client.get(inbox_url)
        self.assertEqual(resp_inbox.status_code, 200)
        inbox_data = resp_inbox.json()
        self.assertEqual(inbox_data["total_sessions"], 1)
        self.assertEqual(inbox_data["sessions"][0]["last_message"]["content"], "Bisa kak, siap kirim.")

        # 4. Ambil seluruh riwayat pesan (scroll ke atas)
        msg_url = reverse("chat:get_session_messages", args=[direct_session.id])
        resp_msgs = self.client.get(msg_url)
        self.assertEqual(resp_msgs.status_code, 200)
        self.assertEqual(len(resp_msgs.json()["messages"]), 2)

    def test_seller_knowledge_base_crud(self):
        self.client.login(username="seller@test.com", password="password123")
        list_url = reverse("chat:seller_knowledge_list_create")

        # Create
        create_resp = self.client.post(list_url, data=json.dumps({
            "product_id": "P9",
            "product_name": "Tumbler Kaca",
            "question": "Apakah tahan panas?",
            "answer": "Tahan hingga 120 derajat Celsius.",
        }), content_type="application/json")
        self.assertEqual(create_resp.status_code, 201)
        item_id = create_resp.json()["knowledge"]["id"]

        # Read
        get_resp = self.client.get(list_url)
        self.assertEqual(get_resp.status_code, 200)

        # Update
        detail_url = reverse("chat:seller_knowledge_detail", args=[item_id])
        patch_resp = self.client.patch(detail_url, data=json.dumps({
            "answer": "Tahan hingga 150 derajat Celsius."
        }), content_type="application/json")
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(ProductKnowledge.objects.get(id=item_id).answer, "Tahan hingga 150 derajat Celsius.")

        # Delete
        del_resp = self.client.delete(detail_url)
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(ProductKnowledge.objects.filter(id=item_id).exists())

    def test_seller_chat_settings_api(self):
        self.client.login(username="seller@test.com", password="password123")
        url = reverse("chat:seller_chat_settings")

        # GET: Read default settings
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["settings"]["is_auto_reply_enabled"])

        # PUT: Update settings
        update_data = {
            "bot_name": "EucalypBot",
            "welcome_message": "Halo dari Toko Eucalyptus!",
            "operating_hours_start": "09:00",
            "operating_hours_end": "17:00",
            "closed_message": "Toko sedang tutup. Harap tinggalkan pesan.",
            "is_auto_reply_enabled": True,
        }
        resp_put = self.client.put(url, data=json.dumps(update_data), content_type="application/json")
        self.assertEqual(resp_put.status_code, 200)
        self.assertEqual(resp_put.json()["settings"]["bot_name"], "EucalypBot")
        self.assertEqual(resp_put.json()["settings"]["welcome_message"], "Halo dari Toko Eucalyptus!")

    @patch("apps.chat.views._is_store_open", return_value=False)
    def test_outside_operating_hours_reply(self, mock_open):
        # Configure seller settings to be closed right now
        settings_obj, _ = SellerChatSettings.objects.get_or_create(seller=self.seller)
        settings_obj.closed_message = "Toko sedang istirahat malam."
        settings_obj.save()

        self.client.login(username="buyer@test.com", password="password123")
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        url = reverse("chat:send_ai_message", args=[session.id])
        resp = self.client.post(url, data=json.dumps({"content": "Halo apa kabar?"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("is_closed"))
        self.assertIn("Toko sedang istirahat malam.", data["reply"])

    def test_storewide_keywords_and_toggle(self):
        self.client.login(username="seller@test.com", password="password123")
        list_url = reverse("chat:seller_knowledge_list_create")

        # 1. Create a store-wide keyword without product_id
        create_resp = self.client.post(list_url, data=json.dumps({
            "product_id": None,
            "product_name": "",
            "question": "Ongkir ke Jakarta berapa?",
            "answer": "Gratis ongkir untuk pesanan di atas Rp100.000.",
        }), content_type="application/json")
        self.assertEqual(create_resp.status_code, 201)
        kw_id = create_resp.json()["knowledge"]["id"]
        kw = ProductKnowledge.objects.get(id=kw_id)
        self.assertIsNone(kw.product_id)
        self.assertTrue(kw.is_active)

        # 2. Toggle active/inactive
        toggle_url = reverse("chat:seller_knowledge_toggle", args=[kw_id])
        t_resp1 = self.client.post(toggle_url)
        self.assertEqual(t_resp1.status_code, 200)
        self.assertFalse(t_resp1.json()["is_active"])

        t_resp2 = self.client.post(toggle_url)
        self.assertEqual(t_resp2.status_code, 200)
        self.assertTrue(t_resp2.json()["is_active"])

    def test_buyer_inbox_filtering_and_archive(self):
        self.client.login(username="buyer@test.com", password="password123")

        session1 = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
        )
        ChatMessage.objects.create(
            session=session1,
            sender=self.seller,
            sender_type=ChatMessage.SENDER_SELLER,
            content="Halo pembeli!",
            is_read=False,
        )

        inbox_url = reverse("chat:buyer_inbox_sessions")

        # 1. Tab Semua
        resp = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["sessions"]), 1)
        self.assertEqual(resp.json()["sessions"][0]["unread_count"], 1)

        # 2. Tab Belum Dibaca
        resp_unread = self.client.get(f"{inbox_url}?tab=belum_dibaca")
        self.assertEqual(resp_unread.status_code, 200)
        self.assertEqual(len(resp_unread.json()["sessions"]), 1)

        # 3. Toggle Archive
        archive_url = reverse("chat:toggle_archive_session", args=[session1.id])
        arc_resp = self.client.post(archive_url)
        self.assertEqual(arc_resp.status_code, 200)
        self.assertTrue(arc_resp.json()["is_archived"])

        # 4. Tab Diarsipkan
        resp_archived = self.client.get(f"{inbox_url}?tab=diarsipkan")
        self.assertEqual(resp_archived.status_code, 200)
        self.assertEqual(len(resp_archived.json()["sessions"]), 1)

        # In Tab Semua, archived session is hidden
        resp_semua_after = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(len(resp_semua_after.json()["sessions"]), 0)

    def test_buyer_inbox_no_duplicate_stores_after_escalation(self):
        self.client.login(username="buyer@test.com", password="password123")
        inbox_url = reverse("chat:buyer_inbox_sessions")

        # 1. Mulai sesi AI awal
        ai_session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
            status=ChatSession.STATUS_ACTIVE,
        )
        ChatMessage.objects.create(
            session=ai_session,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Tanya produk ke bot"
        )

        resp1 = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(len(resp1.json()["sessions"]), 1)
        self.assertEqual(resp1.json()["sessions"][0]["id"], str(ai_session.id))

        # 2. Eskalasi / beralih dari mode chat AI ke penjual langsung
        escalate_url = reverse("chat:escalate_to_seller", args=[ai_session.id])
        esc_resp = self.client.post(escalate_url)
        self.assertEqual(esc_resp.status_code, 200)
        direct_session_id = esc_resp.json()["direct_session_id"]

        # 3. Cek inbox pembeli: Toko TIDAK boleh duplikat (harus tepat 1 sesi, yaitu sesi direct)
        resp2 = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(resp2.status_code, 200)
        sessions = resp2.json()["sessions"]
        self.assertEqual(len(sessions), 1, "Daftar toko di inbox tidak boleh duplikat setelah eskalasi")
        self.assertEqual(sessions[0]["id"], direct_session_id)
        self.assertEqual(sessions[0]["session_type"], ChatSession.TYPE_DIRECT)

        # 3b. Ketika pembeli melihat isi chat direct, unread_count harus 0 (badge notifikasi hilang)
        msg_url = reverse("chat:get_session_messages", args=[direct_session_id])
        msg_resp = self.client.get(msg_url)
        self.assertEqual(msg_resp.status_code, 200)

        resp_badge_check = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(resp_badge_check.json()["sessions"][0]["unread_count"], 0)
        resp_tab_unread = self.client.get(f"{inbox_url}?tab=belum_dibaca")
        self.assertEqual(len(resp_tab_unread.json()["sessions"]), 0)

        # 4. Jika pembeli membuka 'Tanya Produk & Toko' dengan seller yang sama,
        # sesi beralih kembali ke AI session dengan riwayat tersimpan (sesuai permintaan user: selalu dimulai dengan AI chatbot)
        create_url = reverse("chat:get_or_create_ai_session")
        create_resp = self.client.post(
            create_url,
            data=json.dumps({"seller_id": self.seller.id, "products": []}),
            content_type="application/json"
        )
        self.assertEqual(create_resp.status_code, 200)
        self.assertEqual(create_resp.json()["session_type"], ChatSession.TYPE_AI)
        new_ai_session_id = create_resp.json()["session_id"]

        # 5. Tetap tidak ada duplikasi toko di inbox pembeli
        resp3 = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(len(resp3.json()["sessions"]), 1)
        self.assertEqual(resp3.json()["sessions"][0]["id"], new_ai_session_id)

    def test_seller_inbox_unreplied_tab(self):
        self.client.login(username="seller@test.com", password="password123")

        session1 = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
        )
        ChatMessage.objects.create(
            session=session1,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Kak mau tanya produk ini.",
            is_read=False,
        )

        inbox_url = reverse("chat:seller_inbox_sessions")

        # Tab belum_dibalas
        resp = self.client.get(f"{inbox_url}?tab=belum_dibalas")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["sessions"]), 1)

        # Once seller replies, it leaves belum_dibalas
        ChatMessage.objects.create(
            session=session1,
            sender=self.seller,
            sender_type=ChatMessage.SENDER_SELLER,
            content="Halo kak, ada yang bisa dibantu?",
            is_read=True,
        )
        resp_after = self.client.get(f"{inbox_url}?tab=belum_dibalas")
        self.assertEqual(len(resp_after.json()["sessions"]), 0)

    def test_submit_session_rating_api(self):
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
        )
        url = reverse("chat:submit_session_rating", args=[session.id])

        # Seller cannot rate
        self.client.login(username="seller@test.com", password="password123")
        resp_fail = self.client.post(url, data=json.dumps({"rating": 5}), content_type="application/json")
        self.assertEqual(resp_fail.status_code, 403)

        # Buyer can rate
        self.client.login(username="buyer@test.com", password="password123")
        resp_success = self.client.post(url, data=json.dumps({
            "rating": 5,
            "feedback": "Pelayanan sangat cepat dan ramah!",
        }), content_type="application/json")
        self.assertEqual(resp_success.status_code, 200)
        self.assertEqual(SessionRating.objects.get(session=session).rating, 5)

        # Invalid rating
        resp_invalid = self.client.post(url, data=json.dumps({"rating": 10}), content_type="application/json")
        self.assertEqual(resp_invalid.status_code, 400)

    def test_submit_user_report_api(self):
        url = reverse("chat:submit_user_report")
        self.client.login(username="seller@test.com", password="password123")

        # Report self should fail
        resp_self = self.client.post(url, data=json.dumps({
            "reported_user_id": self.seller.id,
            "reason": "Test",
        }), content_type="application/json")
        self.assertEqual(resp_self.status_code, 400)

        # Report buyer succeeds
        resp_success = self.client.post(url, data=json.dumps({
            "reported_user_id": self.buyer.id,
            "reason": "Pembeli menggunakan kata-kata kasar.",
        }), content_type="application/json")
        self.assertEqual(resp_success.status_code, 201)
        report_id = resp_success.json()["report_id"]
        self.assertEqual(UserReport.objects.get(id=report_id).reason, "Pembeli menggunakan kata-kata kasar.")

    def test_broadcast_channel_apis(self):
        # 1. Channel auto-created by signal for seller
        channel = self.seller.broadcast_channel
        channel.name = "Channel Toko Eucalyptus"
        channel.description = "Informasi promo dan tips hidup ramah lingkungan"
        channel.followers_count = 150
        channel.save()

        # 2. List channels (Buyer vs Seller)
        self.client.login(username="buyer@test.com", password="password123")
        list_url = reverse("chat:list_broadcast_channels")
        resp_list_empty = self.client.get(list_url)
        self.assertEqual(resp_list_empty.status_code, 200)
        self.assertEqual(resp_list_empty.json()["total"], 0)

        # Buyer follows channel -> now appears in list
        channel.followers.add(self.buyer)
        resp_list = self.client.get(list_url)
        self.assertEqual(resp_list.status_code, 200)
        self.assertEqual(resp_list.json()["total"], 1)
        self.assertFalse(resp_list.json()["channels"][0]["is_owner"])

        self.client.login(username="seller@test.com", password="password123")
        resp_list_seller = self.client.get(list_url)
        self.assertEqual(resp_list_seller.status_code, 200)
        self.assertTrue(resp_list_seller.json()["channels"][0]["is_owner"])
        self.assertIsNotNone(resp_list_seller.json()["my_channel"])
        self.assertEqual(resp_list_seller.json()["my_channel"]["id"], channel.id)

        # 3. Buyer cannot post to broadcast
        self.client.login(username="buyer@test.com", password="password123")
        send_url = reverse("chat:send_broadcast_message", args=[channel.id])
        resp_forbidden = self.client.post(send_url, data=json.dumps({"content": "Promo palsu"}), content_type="application/json")
        self.assertEqual(resp_forbidden.status_code, 403)

        # 4. Seller posts broadcast message
        self.client.login(username="seller@test.com", password="password123")
        resp_send = self.client.post(send_url, data=json.dumps({"content": "Diskon 20% khusus hari ini!"}), content_type="application/json")
        self.assertEqual(resp_send.status_code, 201)
        self.assertEqual(channel.messages.count(), 1)

        # 5. Buyer reads broadcast message and view count increments
        self.client.login(username="buyer@test.com", password="password123")
        msg_url = reverse("chat:get_broadcast_messages", args=[channel.id])
        resp_msgs = self.client.get(msg_url)
        self.assertEqual(resp_msgs.status_code, 200)
        self.assertEqual(len(resp_msgs.json()["messages"]), 1)
        self.assertEqual(BroadcastMessage.objects.first().viewed_count, 1)

    def test_frontend_chat_pages_render(self):
        # 1. Buyer Chat Page (Screen 1, Screen 7, Screen 8)
        self.client.login(username="buyer@test.com", password="password123")
        resp_buyer = self.client.get(reverse("chat:buyer_chat"))
        self.assertEqual(resp_buyer.status_code, 200)
        self.assertContains(resp_buyer, "BhumiLestari")
        self.assertContains(resp_buyer, "Ratingmu terhadap percakapan tadi")
        self.assertContains(resp_buyer, "Laporkan Pengguna Ini")

        # 2. Seller Chat Page (Screen 2 & Screen 8)
        self.client.login(username="seller@test.com", password="password123")
        resp_seller = self.client.get(reverse("chat:seller_chat"))
        self.assertEqual(resp_seller.status_code, 200)
        self.assertContains(resp_seller, "Belum dibalas")
        self.assertContains(resp_seller, "Laporkan Pengguna Ini")

        # 3. Seller Welcome Settings Page (Screen 3)
        resp_settings = self.client.get(reverse("chat:seller_settings"))
        self.assertEqual(resp_settings.status_code, 200)
        self.assertContains(resp_settings, "Pengaturan Sambutan")
        self.assertContains(resp_settings, "Beri Nama Botmu")
        self.assertContains(resp_settings, "Jam Operasional Toko")
        self.assertContains(resp_settings, "Pesan Saat Toko Tutup")

        # 4. Seller Keywords Page (Screen 4)
        ProductKnowledge.objects.create(
            seller=self.seller,
            question="Ongkir",
            answer="Ongkir dihitung saat checkout kak!",
            is_active=True,
        )
        resp_keywords = self.client.get(reverse("chat:seller_keywords"))
        self.assertEqual(resp_keywords.status_code, 200)
        self.assertContains(resp_keywords, "Balasan Kata Kunci")
        self.assertContains(resp_keywords, "Ongkir dihitung saat checkout kak!")
        self.assertContains(resp_keywords, "Tambah balasan")

        # 5. Broadcast Page (Screen 5 & Screen 6)
        resp_broadcast = self.client.get(reverse("chat:broadcast"))
        self.assertEqual(resp_broadcast.status_code, 200)
        self.assertContains(resp_broadcast, "Anda tidak punya akses untuk mengirim pesan pada channel ini")
        self.assertContains(resp_broadcast, "broadcastComposerFooter")
        self.assertTrue(BroadcastChannel.objects.filter(seller=self.seller).exists())

    def test_all_sellers_automatically_have_broadcast_channel(self):
        new_seller = User.objects.create_user(
            username="seller.baru@bhumilestari.com",
            email="seller.baru@bhumilestari.com",
            password="password123",
            role="seller",
            full_name="Toko Organik Sejahtera"
        )
        self.assertTrue(BroadcastChannel.objects.filter(seller=new_seller).exists())
        self.assertEqual(new_seller.broadcast_channel.name, "Toko Organik Sejahtera")

    def test_broadcast_channel_archive_and_tabs(self):
        channel = self.seller.broadcast_channel
        channel.name = "Channel Toko Lestari"
        channel.followers_count = 100
        channel.save()
        channel.followers.add(self.buyer)

        self.client.login(username="buyer@test.com", password="password123")
        archive_url = reverse("chat:toggle_archive_broadcast_channel", args=[channel.id])
        list_url = reverse("chat:list_broadcast_channels")

        # 1. Archive channel
        arc_resp = self.client.post(archive_url)
        self.assertEqual(arc_resp.status_code, 200)
        self.assertTrue(arc_resp.json()["is_archived"])

        # 2. Check tab diarsipkan
        resp_diarsipkan = self.client.get(f"{list_url}?tab=diarsipkan")
        self.assertEqual(resp_diarsipkan.status_code, 200)
        self.assertEqual(len(resp_diarsipkan.json()["channels"]), 1)
        self.assertEqual(resp_diarsipkan.json()["channels"][0]["id"], channel.id)

        # 3. Check tab semua (archived is excluded)
        resp_semua = self.client.get(f"{list_url}?tab=semua")
        self.assertEqual(resp_semua.status_code, 200)
        self.assertEqual(len(resp_semua.json()["channels"]), 0)

        # 4. Unarchive channel
        unarc_resp = self.client.post(archive_url)
        self.assertEqual(unarc_resp.status_code, 200)
        self.assertFalse(unarc_resp.json()["is_archived"])

        resp_semua_after = self.client.get(f"{list_url}?tab=semua")
        self.assertEqual(len(resp_semua_after.json()["channels"]), 1)

    def test_follow_and_unfollow_broadcast_channel_api(self):
        """
        Menguji alur ikuti (follow) dan berhenti ikuti (unfollow) saluran siaran:
        1. Validasi proteksi HTTP Method (hanya POST yang diizinkan, GET -> 405).
        2. Validasi pencegahan follow diri sendiri (pemilik/seller tidak bisa follow -> 400).
        3. Pembeli melakukan follow: status 200, is_following=True, followers_count bertambah.
        4. Verifikasi status is_following pada get_broadcast_messages dan list_broadcast_channels.
        5. Pembeli melakukan unfollow: status 200, is_following=False, followers_count berkurang.
        """
        channel = self.seller.broadcast_channel
        channel.name = "Saluran Toko Hijau"
        channel.followers_count = 0
        channel.save()
        follow_url = reverse("chat:toggle_follow_broadcast_channel", args=[channel.id])
        messages_url = reverse("chat:get_broadcast_messages", args=[channel.id])
        list_url = reverse("chat:list_broadcast_channels")

        # 1. GET request ditolak dengan 405 Method Not Allowed
        self.client.login(username="buyer@test.com", password="password123")
        resp_get = self.client.get(follow_url)
        self.assertEqual(resp_get.status_code, 405)

        # 2. Seller mencoba follow channel miliknya sendiri -> 400 Bad Request
        self.client.login(username="seller@test.com", password="password123")
        resp_owner = self.client.post(follow_url)
        self.assertEqual(resp_owner.status_code, 400)
        self.assertIn("tidak dapat mengikuti channel Anda sendiri", resp_owner.json().get("message", ""))

        # 3. Buyer melakukan follow pertama kali
        self.client.login(username="buyer@test.com", password="password123")
        resp_follow = self.client.post(follow_url)
        self.assertEqual(resp_follow.status_code, 200)
        follow_data = resp_follow.json()
        self.assertEqual(follow_data["status"], "success")
        self.assertTrue(follow_data["is_following"])
        self.assertEqual(follow_data["followers_count"], 1)

        # Verifikasi langsung pada database
        channel.refresh_from_db()
        self.assertEqual(channel.followers_count, 1)
        self.assertTrue(channel.followers.filter(id=self.buyer.id).exists())

        # 4. Verifikasi endpoint messages dan list channels merefleksikan is_following = True
        resp_msgs = self.client.get(messages_url)
        self.assertEqual(resp_msgs.status_code, 200)
        self.assertTrue(resp_msgs.json()["channel"]["is_following"])
        self.assertEqual(resp_msgs.json()["channel"]["followers_count"], 1)

        resp_list = self.client.get(list_url)
        self.assertEqual(resp_list.status_code, 200)
        matched = next((c for c in resp_list.json()["channels"] if c["id"] == channel.id), None)
        self.assertIsNotNone(matched)
        self.assertTrue(matched["is_following"])

        # 5. Buyer melakukan follow kedua kali (Unfollow)
        resp_unfollow = self.client.post(follow_url)
        self.assertEqual(resp_unfollow.status_code, 200)
        unfollow_data = resp_unfollow.json()
        self.assertEqual(unfollow_data["status"], "success")
        self.assertFalse(unfollow_data["is_following"])
        self.assertEqual(unfollow_data["followers_count"], 0)

        # Verifikasi langsung pada database
        channel.refresh_from_db()
        self.assertEqual(channel.followers_count, 0)
        self.assertFalse(channel.followers.filter(id=self.buyer.id).exists())

        # Verifikasi get_broadcast_messages merefleksikan is_following = False
        resp_msgs_after = self.client.get(messages_url)
        self.assertEqual(resp_msgs_after.status_code, 200)
        self.assertFalse(resp_msgs_after.json()["channel"]["is_following"])
        self.assertEqual(resp_msgs_after.json()["channel"]["followers_count"], 0)

    def test_add_channel_to_list_and_explore_api(self):
        """
        Menguji fitur Tambah Saluran ke Channel List dan Jelajahi Saluran (Explore):
        1. Buyer membuka channel list: awalnya 0 saluran (karena belum follow dan belum add).
        2. Endpoint explore_broadcast_channels mengembalikan saluran yang tersedia (bukan milik sendiri).
        3. Buyer menambahkan channel ke list via add_broadcast_channel_to_list_api (POST).
           - Channel sukses masuk ke relasi added_by.
           - Channel TIDAK otomatis terfollow (is_following=False, followers_count=0).
        4. Channel sekarang muncul di list_broadcast_channels_api pembeli dengan is_following=False.
        5. Pemilik channel tidak dapat menambahkan channelnya sendiri (status 400).
        6. Request GET ke endpoint add ditolak dengan status 405.
        """
        channel = self.seller.broadcast_channel
        channel.name = "Saluran Toko Herbal Lestari"
        channel.followers_count = 0
        channel.save()

        self.client.login(username="buyer@test.com", password="password123")
        list_url = reverse("chat:list_broadcast_channels")
        explore_url = reverse("chat:explore_broadcast_channels")
        add_url = reverse("chat:add_broadcast_channel_to_list", args=[channel.id])

        # 1. Buyer channel list kosong awalnya
        resp_list_initial = self.client.get(list_url)
        self.assertEqual(resp_list_initial.status_code, 200)
        self.assertEqual(resp_list_initial.json()["total"], 0)

        # 2. Explore channels
        resp_explore = self.client.get(explore_url)
        self.assertEqual(resp_explore.status_code, 200)
        explore_data = resp_explore.json()
        self.assertEqual(explore_data["status"], "success")
        self.assertTrue(any(c["id"] == channel.id for c in explore_data["channels"]))

        # Explore dengan query pencarian cocok
        resp_search = self.client.get(f"{explore_url}?q=Herbal")
        self.assertEqual(resp_search.status_code, 200)
        self.assertEqual(len(resp_search.json()["channels"]), 1)
        self.assertEqual(resp_search.json()["channels"][0]["id"], channel.id)

        # 3. GET request ke add ditolak (405)
        resp_get_add = self.client.get(add_url)
        self.assertEqual(resp_get_add.status_code, 405)

        # 4. Tambahkan channel ke list via POST
        resp_add = self.client.post(add_url)
        self.assertEqual(resp_add.status_code, 200)
        add_data = resp_add.json()
        self.assertEqual(add_data["status"], "success")
        self.assertFalse(add_data["channel"]["is_following"]) # Tidak otomatis terfollow

        # Verifikasi di database: ada di added_by, TIDAK ada di followers
        channel.refresh_from_db()
        self.assertTrue(channel.added_by.filter(id=self.buyer.id).exists())
        self.assertFalse(channel.followers.filter(id=self.buyer.id).exists())
        self.assertEqual(channel.followers_count, 0)

        # 5. Channel sekarang muncul di channel list pembeli
        resp_list_after = self.client.get(list_url)
        self.assertEqual(resp_list_after.status_code, 200)
        self.assertEqual(resp_list_after.json()["total"], 1)
        item = resp_list_after.json()["channels"][0]
        self.assertEqual(item["id"], channel.id)
        self.assertFalse(item["is_following"])

        # 6. Pemilik (seller) tidak dapat menambahkan salurannya sendiri
        self.client.login(username="seller@test.com", password="password123")
        resp_seller_add = self.client.post(add_url)
        self.assertEqual(resp_seller_add.status_code, 400)
        self.assertIn("saluran toko Anda sendiri", resp_seller_add.json().get("message", ""))

    def test_search_sellers_api_debounce_and_random(self):
        self.client.login(username="buyer@test.com", password="password123")
        url = reverse("chat:search_sellers")

        from apps.users.models import SellerProfile
        seller_profile, _ = SellerProfile.objects.get_or_create(user=self.seller, defaults={"store_name": "Toko Lestari"})

        # 1. Query kosong: harus return toko random
        resp_empty = self.client.get(url)
        self.assertEqual(resp_empty.status_code, 200)
        data_empty = resp_empty.json()
        self.assertEqual(data_empty["status"], "success")
        self.assertGreaterEqual(len(data_empty["sellers"]), 1)

        # 2. Query kata kunci toko yang cocok
        store_keyword = seller_profile.store_name[:4]
        resp_q = self.client.get(f"{url}?q={store_keyword}")
        self.assertEqual(resp_q.status_code, 200)
        data_q = resp_q.json()
        self.assertEqual(data_q["status"], "success")
        self.assertTrue(any(s["id"] == self.seller.id for s in data_q["sellers"]))

        # 3. Query kata kunci toko yang tidak ada
        resp_none = self.client.get(f"{url}?q=tidak_ada_toko_xyz123")
        self.assertEqual(resp_none.status_code, 200)
        self.assertEqual(len(resp_none.json()["sellers"]), 0)

    def test_search_products_api_filtered_by_seller(self):
        self.client.login(username="buyer@test.com", password="password123")
        url = reverse("dashboard:api_products")

        # 1. Buat produk untuk seller ini
        from apps.users.models import SellerProfile
        from apps.products.models import Product
        seller_profile, _ = SellerProfile.objects.get_or_create(user=self.seller, defaults={"store_name": "Toko Lestari"})
        p1 = Product.objects.create(
            seller=seller_profile,
            name="Sabun Cuci Piring Herbal",
            price=15000,
            stock=10
        )
        p2 = Product.objects.create(
            seller=seller_profile,
            name="Sikat Gigi Kayu Cendana",
            price=20000,
            stock=5
        )

        # 2. Query produk toko tanpa keyword: return semua produk toko ini
        resp_all = self.client.get(f"{url}?seller_id={self.seller.id}")
        self.assertEqual(resp_all.status_code, 200)
        data_all = resp_all.json()
        self.assertEqual(data_all["status"], "success")
        self.assertEqual(len(data_all["products"]), 2)

        # 3. Query produk dengan keyword (title / q): filter sesuai nama produk
        resp_search = self.client.get(f"{url}?seller_id={self.seller.id}&title=sabun")
        self.assertEqual(resp_search.status_code, 200)
        data_search = resp_search.json()
        self.assertEqual(len(data_search["products"]), 1)
        self.assertEqual(data_search["products"][0]["product_name"], "Sabun Cuci Piring Herbal")

        resp_search_q = self.client.get(f"{url}?seller_id={self.seller.id}&q=sabun")
        self.assertEqual(resp_search_q.status_code, 200)
        data_search_q = resp_search_q.json()
        self.assertEqual(len(data_search_q["products"]), 1)
        self.assertEqual(data_search_q["products"][0]["name"], "Sabun Cuci Piring Herbal")

    def test_switch_to_ai_session_preserves_history(self):
        self.client.login(username="buyer@test.com", password="password123")

        # 1. Buat direct session aktif
        direct_session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
            status=ChatSession.STATUS_ACTIVE,
        )
        msg_buyer = ChatMessage.objects.create(
            session=direct_session,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Halo penjual, apakah harga masih bisa nego?",
            is_read=True,
        )
        msg_seller = ChatMessage.objects.create(
            session=direct_session,
            sender=self.seller,
            sender_type=ChatMessage.SENDER_SELLER,
            content="Halo, mohon maaf harga kami sudah pas ya.",
            is_read=True,
        )

        # 2. Panggil switch-to-ai
        switch_url = reverse("chat:switch_to_ai_session", args=[direct_session.id])
        resp = self.client.post(switch_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["session_type"], ChatSession.TYPE_AI)
        ai_session_id = data["ai_session_id"]

        # 3. Verifikasi status direct_session menjadi resolved
        direct_session.refresh_from_db()
        self.assertEqual(direct_session.status, ChatSession.STATUS_RESOLVED)

        # 4. Verifikasi sesi AI baru aktif dan memuat semua riwayat chat direct
        ai_session = ChatSession.objects.get(id=ai_session_id)
        self.assertEqual(ai_session.status, ChatSession.STATUS_ACTIVE)
        self.assertEqual(ai_session.session_type, ChatSession.TYPE_AI)

        ai_msg_contents = list(ai_session.messages.values_list("content", flat=True))
        self.assertIn("Halo penjual, apakah harga masih bisa nego?", ai_msg_contents)
        self.assertIn("Halo, mohon maaf harga kami sudah pas ya.", ai_msg_contents)
        self.assertTrue(any("--- Anda kini beralih kembali ke Asisten AI" in c for c in ai_msg_contents))

        # 5. Verifikasi inbox sessions pembeli menampilkan 1 entri (deduplikasi per toko)
        inbox_url = reverse("chat:buyer_inbox_sessions")
        inbox_resp = self.client.get(f"{inbox_url}?tab=semua")
        self.assertEqual(inbox_resp.status_code, 200)
        inbox_data = inbox_resp.json()
        self.assertEqual(inbox_data["total_sessions"], 1)
        self.assertEqual(inbox_data["sessions"][0]["id"], str(ai_session.id))
        self.assertEqual(inbox_data["sessions"][0]["session_type"], ChatSession.TYPE_AI)

    def test_get_or_create_ai_session_always_starts_ai_even_with_prior_direct(self):
        self.client.login(username="buyer@test.com", password="password123")

        # Buat direct session aktif sebelumnya
        direct_session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
            status=ChatSession.STATUS_ACTIVE,
        )
        ChatMessage.objects.create(
            session=direct_session,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Permisi mau tanya stok sabun.",
            is_read=True,
        )

        # Buyer membuka modal Tanya Produk & Toko dan memilih seller ini
        url = reverse("chat:get_or_create_ai_session")
        resp = self.client.post(
            url,
            data=json.dumps({"seller_id": self.seller.id, "products": [{"product_id": "PRD-99", "product_name": "Sabun Alami"}]}),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["session_type"], ChatSession.TYPE_AI)

        # Direct session lama sudah resolved dan beralih ke sesi AI
        direct_session.refresh_from_db()
        self.assertEqual(direct_session.status, ChatSession.STATUS_RESOLVED)

        # Riwayat tetap tersimpan di sesi AI
        ai_session = ChatSession.objects.get(id=data["session_id"])
        self.assertTrue(ai_session.messages.filter(content="Permisi mau tanya stok sabun.").exists())
        self.assertEqual(ai_session.product_contexts.count(), 1)




