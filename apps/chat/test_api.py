from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token

from apps.users.models import SellerProfile

from .models import (
    BroadcastChannel,
    ChatMessage,
    ChatSession,
    ProductKnowledge,
    SessionRating,
    UserReport,
)


User = get_user_model()


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ChatDRFAPITests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            username="buyer_chat_api",
            email="buyer_chat_api@example.com",
            password="password123",
            full_name="Pembeli Chat",
            role="buyer",
        )
        self.seller = User.objects.create_user(
            username="seller_chat_api",
            email="seller_chat_api@example.com",
            password="password123",
            full_name="Penjual Chat",
            role="seller",
        )
        self.seller_profile = SellerProfile.objects.create(
            user=self.seller,
            store_name="Toko Ramah Lingkungan",
        )
        self.outsider = User.objects.create_user(
            username="outsider_chat_api",
            email="outsider_chat_api@example.com",
            password="password123",
            full_name="Outsider",
            role="buyer",
        )
        self.buyer_token = Token.objects.create(user=self.buyer)
        self.seller_token = Token.objects.create(user=self.seller)

    def test_search_sellers_with_token_auth(self):
        url = reverse("chat_api:search-sellers")
        res = self.client.get(
            url,
            {"q": "Ramah"},
            HTTP_AUTHORIZATION=f"Token {self.buyer_token.key}",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total"], 1)
        self.assertEqual(
            data["sellers"][0]["store_name"],
            "Toko Ramah Lingkungan",
        )

    def test_create_ai_session_and_manage_product_contexts(self):
        create_url = reverse("chat_api:ai-session-create")
        self.client.force_login(self.seller)
        res_self = self.client.post(
            create_url,
            data={"seller_id": self.seller.id},
            content_type="application/json",
        )
        self.assertEqual(res_self.status_code, 400)

        self.client.force_login(self.buyer)
        res = self.client.post(
            create_url,
            data={
                "seller_id": self.seller.id,
                "products": [
                    {"product_id": "p-1", "product_name": "Sabun Bambu"},
                ],
            },
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        session_id = res.json()["session_id"]
        self.assertEqual(len(res.json()["product_contexts"]), 1)

        # Add another product context
        prod_url = reverse(
            "chat_api:session-products",
            kwargs={"session_id": session_id},
        )
        res_add = self.client.post(
            prod_url,
            data={
                "products": [
                    {"product_id": "p-2", "product_name": "Sikat Kayu"},
                ]
            },
            content_type="application/json",
        )
        self.assertEqual(res_add.status_code, 200)
        self.assertEqual(len(res_add.json()["all_product_contexts"]), 2)

        # Delete one product context
        res_del = self.client.delete(f"{prod_url}?product_id=p-1")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(len(res_del.json()["all_product_contexts"]), 1)

        # Delete all via /products/delete/
        del_all_url = reverse(
            "chat_api:session-products-delete",
            kwargs={"session_id": session_id},
        )
        res_del_all = self.client.post(
            del_all_url,
            data={"product_id": "all"},
            content_type="application/json",
        )
        self.assertEqual(res_del_all.status_code, 200)
        self.assertEqual(len(res_del_all.json()["all_product_contexts"]), 0)

    @patch("apps.chat.api_views._is_store_open", return_value=True)
    @patch(
        "apps.chat.api_views.query_openrouter",
        return_value="Sabun ini 100% organik dan biodegradable.",
    )
    def test_send_ai_message_and_handover_flows(
        self,
        _mock_ai,
        _mock_open,
    ):
        self.client.force_login(self.buyer)
        create_res = self.client.post(
            reverse("chat_api:ai-session-create"),
            data={"seller_id": self.seller.id},
            content_type="application/json",
        )
        session_id = create_res.json()["session_id"]

        send_url = reverse(
            "chat_api:send-ai-message",
            kwargs={"session_id": session_id},
        )
        res = self.client.post(
            send_url,
            data={"content": "Apakah sabun ini organik?"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["handover"])
        self.assertIn("organik", res.json()["reply"])

        # Escalate to seller manually
        escalate_url = reverse(
            "chat_api:escalate-to-seller",
            kwargs={"session_id": session_id},
        )
        res_esc = self.client.post(escalate_url)
        self.assertEqual(res_esc.status_code, 200)
        direct_session_id = res_esc.json()["direct_session_id"]

        # Send direct messages as buyer and seller
        direct_send_url = reverse(
            "chat_api:send-direct-message",
            kwargs={"session_id": direct_session_id},
        )
        res_dm_buyer = self.client.post(
            direct_send_url,
            data={"content": "Halo penjual, stok masih ada?"},
            content_type="application/json",
        )
        self.assertEqual(res_dm_buyer.status_code, 200)

        self.client.force_login(self.seller)
        res_dm_seller = self.client.post(
            direct_send_url,
            data={"content": "Masih ready banyak kak!"},
            content_type="application/json",
        )
        self.assertEqual(res_dm_seller.status_code, 200)

        # Buyer reads messages and switches back to AI
        self.client.force_login(self.buyer)
        msgs_url = reverse(
            "chat_api:session-messages",
            kwargs={"session_id": direct_session_id},
        )
        res_msgs = self.client.get(msgs_url)
        self.assertEqual(res_msgs.status_code, 200)
        self.assertTrue(len(res_msgs.json()["messages"]) >= 3)

        switch_url = reverse(
            "chat_api:switch-to-ai",
            kwargs={"session_id": direct_session_id},
        )
        res_switch = self.client.post(switch_url)
        self.assertEqual(res_switch.status_code, 200)
        self.assertEqual(res_switch.json()["session_type"], ChatSession.TYPE_AI)

    def test_inbox_and_archive_session_endpoints(self):
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
            status=ChatSession.STATUS_ACTIVE,
        )
        ChatMessage.objects.create(
            session=session,
            sender=self.buyer,
            sender_type=ChatMessage.SENDER_BUYER,
            content="Pesan belum dibalas",
            is_read=False,
        )

        # Seller inbox checks
        self.client.force_login(self.seller)
        seller_inbox_url = reverse("chat_api:seller-inbox-sessions")
        res_seller = self.client.get(
            seller_inbox_url,
            {"tab": "belum_dibalas"},
        )
        self.assertEqual(res_seller.status_code, 200)
        self.assertEqual(res_seller.json()["total_sessions"], 1)

        # Buyer inbox and archive toggle
        self.client.force_login(self.buyer)
        buyer_inbox_url = reverse("chat_api:buyer-inbox-sessions")
        res_buyer = self.client.get(buyer_inbox_url)
        self.assertEqual(res_buyer.status_code, 200)
        self.assertEqual(res_buyer.json()["total_sessions"], 1)

        archive_url = reverse(
            "chat_api:toggle-archive-session",
            kwargs={"session_id": session.id},
        )
        res_arch = self.client.post(archive_url)
        self.assertEqual(res_arch.status_code, 200)
        self.assertTrue(res_arch.json()["is_archived"])

        res_archived_tab = self.client.get(
            buyer_inbox_url,
            {"tab": "diarsipkan"},
        )
        self.assertEqual(res_archived_tab.json()["total_sessions"], 1)

    def test_seller_settings_and_knowledge_crud(self):
        self.client.force_login(self.seller)
        settings_url = reverse("chat_api:seller-settings")

        res_get = self.client.get(settings_url)
        self.assertEqual(res_get.status_code, 200)

        res_bad_time = self.client.patch(
            settings_url,
            data={"operating_hours_start": "25:99"},
            content_type="application/json",
        )
        self.assertEqual(res_bad_time.status_code, 400)

        res_upd = self.client.patch(
            settings_url,
            data={
                "bot_name": "LestariBot",
                "operating_hours_start": "09:00",
                "operating_hours_end": "18:00",
            },
            content_type="application/json",
        )
        self.assertEqual(res_upd.status_code, 200)
        self.assertEqual(res_upd.json()["settings"]["bot_name"], "LestariBot")

        # Knowledge CRUD
        kw_list_url = reverse("chat_api:seller-knowledge-list")
        res_create = self.client.post(
            kw_list_url,
            data={
                "question": "Apakah bebas plastik?",
                "answer": "Ya, kemasan kami 100% kertas daur ulang.",
            },
            content_type="application/json",
        )
        self.assertEqual(res_create.status_code, 201)
        kw_id = res_create.json()["knowledge"]["id"]

        kw_detail_url = reverse(
            "chat_api:seller-knowledge-detail",
            kwargs={"pk": kw_id},
        )
        res_patch = self.client.patch(
            kw_detail_url,
            data={"answer": "Kemasan 100% kompos alami."},
            content_type="application/json",
        )
        self.assertEqual(res_patch.status_code, 200)
        self.assertEqual(
            res_patch.json()["knowledge"]["answer"],
            "Kemasan 100% kompos alami.",
        )

        kw_toggle_url = reverse(
            "chat_api:seller-knowledge-toggle",
            kwargs={"pk": kw_id},
        )
        res_toggle = self.client.post(kw_toggle_url)
        self.assertEqual(res_toggle.status_code, 200)
        self.assertFalse(res_toggle.json()["is_active"])

        res_del = self.client.delete(kw_detail_url)
        self.assertEqual(res_del.status_code, 200)
        self.assertFalse(ProductKnowledge.objects.filter(id=kw_id).exists())

    def test_rating_and_report_endpoints(self):
        session = ChatSession.objects.create(
            buyer=self.buyer,
            seller=self.seller,
            session_type=ChatSession.TYPE_DIRECT,
        )
        rating_url = reverse(
            "chat_api:session-rating",
            kwargs={"session_id": session.id},
        )
        self.client.force_login(self.seller)
        res_forbidden = self.client.post(
            rating_url,
            data={"rating": 5},
            content_type="application/json",
        )
        self.assertEqual(res_forbidden.status_code, 403)

        self.client.force_login(self.buyer)
        res_rating = self.client.post(
            rating_url,
            data={"rating": 5, "feedback": "Sangat memuaskan!"},
            content_type="application/json",
        )
        self.assertEqual(res_rating.status_code, 200)
        self.assertTrue(SessionRating.objects.filter(session=session).exists())

        report_url = reverse("chat_api:user-report-create")
        res_self_report = self.client.post(
            report_url,
            data={"reported_user_id": self.buyer.id, "reason": "Tes"},
            content_type="application/json",
        )
        self.assertEqual(res_self_report.status_code, 400)

        res_report = self.client.post(
            report_url,
            data={
                "reported_user_id": self.seller.id,
                "session_id": str(session.id),
                "reason": "Respon kurang sopan",
            },
            content_type="application/json",
        )
        self.assertEqual(res_report.status_code, 201)
        self.assertTrue(
            UserReport.objects.filter(
                reporter=self.buyer,
                reported_user=self.seller,
            ).exists()
        )

    def test_broadcast_channels_and_messages_flow(self):
        channel = BroadcastChannel.objects.get(seller=self.seller)

        # Buyer explores, adds, follows, and archives channel
        self.client.force_login(self.buyer)
        explore_url = reverse("chat_api:broadcast-channel-explore")
        res_explore = self.client.get(explore_url)
        self.assertEqual(res_explore.status_code, 200)
        self.assertTrue(res_explore.json()["total"] >= 1)

        add_url = reverse(
            "chat_api:broadcast-add",
            kwargs={"channel_id": channel.id},
        )
        res_add = self.client.post(add_url)
        self.assertEqual(res_add.status_code, 200)
        self.assertFalse(res_add.json()["channel"]["is_following"])

        follow_url = reverse(
            "chat_api:broadcast-follow",
            kwargs={"channel_id": channel.id},
        )
        res_follow = self.client.post(follow_url)
        self.assertEqual(res_follow.status_code, 200)
        self.assertTrue(res_follow.json()["is_following"])
        self.assertEqual(res_follow.json()["followers_count"], 1)

        # Buyer cannot post broadcast message
        send_url = reverse(
            "chat_api:broadcast-send",
            kwargs={"channel_id": channel.id},
        )
        res_buyer_send = self.client.post(
            send_url,
            data={"content": "Halo"},
            content_type="application/json",
        )
        self.assertEqual(res_buyer_send.status_code, 403)

        # Seller posts broadcast message
        self.client.force_login(self.seller)
        res_seller_send = self.client.post(
            send_url,
            data={"content": "Promo Hari Bumi diskon 30%!"},
            content_type="application/json",
        )
        self.assertEqual(res_seller_send.status_code, 201)

        # Buyer reads broadcast messages (increments viewed_count)
        self.client.force_login(self.buyer)
        msgs_url = reverse(
            "chat_api:broadcast-messages",
            kwargs={"channel_id": channel.id},
        )
        res_msgs = self.client.get(msgs_url)
        self.assertEqual(res_msgs.status_code, 200)
        self.assertEqual(res_msgs.json()["messages"][0]["viewed_count"], 1)

        archive_url = reverse(
            "chat_api:broadcast-archive",
            kwargs={"channel_id": channel.id},
        )
        res_arch = self.client.post(archive_url)
        self.assertEqual(res_arch.status_code, 200)
        self.assertTrue(res_arch.json()["is_archived"])
