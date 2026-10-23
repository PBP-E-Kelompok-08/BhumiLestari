from django.urls import path
from apps.chat.views import (
    buyer_chat_view,
    seller_chat_view,
    seller_settings_view,
    seller_keywords_view,
    broadcast_view,
    get_or_create_ai_session_api,
    add_product_context_api,
    delete_product_context_api,
    send_ai_message_api,
    escalate_to_seller_api,
    switch_to_ai_session_api,
    send_direct_message_api,
    get_session_messages_api,
    toggle_archive_session_api,
    buyer_inbox_sessions_api,
    seller_inbox_sessions_api,
    seller_chat_settings_api,
    seller_knowledge_list_create_api,
    seller_knowledge_detail_api,
    seller_knowledge_toggle_api,
    submit_session_rating_api,
    submit_user_report_api,
    list_broadcast_channels_api,
    get_broadcast_messages_api,
    send_broadcast_message_api,
    toggle_archive_broadcast_channel_api,
    search_sellers_api,
    search_products_api,
)

app_name = "chat"

urlpatterns = [
    # Frontend UI Pages (Figma 1:1)
    path("chat/", buyer_chat_view, name="buyer_chat"),
    path("chat/seller/", seller_chat_view, name="seller_chat"),
    path("chat/seller/settings/", seller_settings_view, name="seller_settings"),
    path("chat/seller/keywords/", seller_keywords_view, name="seller_keywords"),
    path("chat/broadcast/", broadcast_view, name="broadcast"),

    # Search APIs (Debounce AJAX / Random Fallback)
    path("chat/api/sellers/search/", search_sellers_api, name="search_sellers"),
    path("chat/api/products/search/", search_products_api, name="search_products"),

    # Buyer & AI Chat Sessions
    path("chat/api/sessions/ai/", get_or_create_ai_session_api, name="get_or_create_ai_session"),
    path("chat/api/sessions/<uuid:session_id>/products/", add_product_context_api, name="add_product_context"),
    path("chat/api/sessions/<uuid:session_id>/products/delete/", delete_product_context_api, name="delete_product_context"),
    path("chat/api/sessions/<uuid:session_id>/send/", send_ai_message_api, name="send_ai_message"),
    path("chat/api/sessions/<uuid:session_id>/escalate-to-seller/", escalate_to_seller_api, name="escalate_to_seller"),
    path("chat/api/sessions/<uuid:session_id>/switch-to-ai/", switch_to_ai_session_api, name="switch_to_ai_session"),

    # Direct Chat & Inbox Management
    path("chat/api/sessions/<uuid:session_id>/direct-send/", send_direct_message_api, name="send_direct_message"),
    path("chat/api/sessions/<uuid:session_id>/messages/", get_session_messages_api, name="get_session_messages"),
    path("chat/api/sessions/<uuid:session_id>/archive/", toggle_archive_session_api, name="toggle_archive_session"),
    path("chat/api/buyer/sessions/", buyer_inbox_sessions_api, name="buyer_inbox_sessions"),
    path("chat/api/seller/sessions/", seller_inbox_sessions_api, name="seller_inbox_sessions"),

    # Seller Settings & Knowledge Base
    path("chat/api/seller/settings/", seller_chat_settings_api, name="seller_chat_settings"),
    path("chat/api/seller/knowledge/", seller_knowledge_list_create_api, name="seller_knowledge_list_create"),
    path("chat/api/seller/knowledge/<int:pk>/", seller_knowledge_detail_api, name="seller_knowledge_detail"),
    path("chat/api/seller/knowledge/<int:pk>/toggle/", seller_knowledge_toggle_api, name="seller_knowledge_toggle"),

    # Feedback & Moderation (Ratings & Reports)
    path("chat/api/sessions/<uuid:session_id>/rating/", submit_session_rating_api, name="submit_session_rating"),
    path("chat/api/reports/", submit_user_report_api, name="submit_user_report"),

    # Store Broadcast Channels
    path("chat/api/broadcast/channels/", list_broadcast_channels_api, name="list_broadcast_channels"),
    path("chat/api/broadcast/channels/<int:channel_id>/messages/", get_broadcast_messages_api, name="get_broadcast_messages"),
    path("chat/api/broadcast/channels/<int:channel_id>/send/", send_broadcast_message_api, name="send_broadcast_message"),
    path("chat/api/broadcast/channels/<int:channel_id>/archive/", toggle_archive_broadcast_channel_api, name="toggle_archive_broadcast_channel"),
]