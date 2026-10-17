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
