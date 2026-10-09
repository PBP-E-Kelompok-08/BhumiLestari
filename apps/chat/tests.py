import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.chat.models import ProductKnowledge, ChatSession, SessionProductContext, ChatMessage
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
        pk = ProductKnowledge.objects.create(
            seller=self.seller,
            product_id="PRD-01",
            product_name="Sabun Batang Bambu",
            question="Apakah alami?",
            answer="Ya, 100% bahan alami.",
        )
        self.assertIn("Sabun Batang Bambu", str(pk))

        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        self.assertEqual(session.status, ChatSession.STATUS_ACTIVE)
        self.assertIn("AI", str(session))

        ctx = SessionProductContext.objects.create(
            session=session,
            product_id="PRD-01",
            product_name="Sabun Batang Bambu",
        )
        self.assertEqual(session.product_contexts.count(), 1)
        self.assertIn("Sabun Batang Bambu", str(ctx))

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

from django.test import Client
from django.urls import reverse

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
        self.assertEqual(session.messages.count(), 2)

    @patch("apps.chat.views.query_openrouter")
    def test_send_ai_message_triggers_handover(self, mock_ai):
        mock_ai.return_value = f"{HANDOVER_TOKEN}: Maaf info garansi belum tersedia, saya alihkan ke penjual."

        self.client.login(username="buyer@test.com", password="password123")
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_AI,
        )
        SessionProductContext.objects.create(session=session, product_id="P1", product_name="Sedotan Bambu")
        ChatMessage.objects.create(session=session, sender=self.buyer, sender_type=ChatMessage.SENDER_BUYER, content="Halo")
        ChatMessage.objects.create(session=session, sender=None, sender_type=ChatMessage.SENDER_AI, content="Halo ada yang bisa dibantu?")

        url = reverse("chat:send_ai_message", args=[session.id])
        payload = {"content": "Apakah ada garansi 1 tahun?"}
        response = self.client.post(url, data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["handover"])
        self.assertIn("direct_session_id", data)

        direct_session_id = data["direct_session_id"]
        direct_session = ChatSession.objects.get(id=direct_session_id)
        self.assertEqual(direct_session.session_type, ChatSession.TYPE_DIRECT)
        self.assertEqual(direct_session.origin_session, session)
        self.assertEqual(direct_session.handover_reason, ChatSession.HANDOVER_UNANSWERED)
        self.assertEqual(direct_session.product_contexts.count(), 1)
        self.assertEqual(direct_session.product_contexts.first().product_id, "P1")

        direct_messages = list(direct_session.messages.order_by("created_at"))
        inherited_msgs = [m for m in direct_messages if m.is_inherited_from_ai]
        self.assertGreaterEqual(len(inherited_msgs), 2)

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
