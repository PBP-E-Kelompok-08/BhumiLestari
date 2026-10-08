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
