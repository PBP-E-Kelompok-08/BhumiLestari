from django.urls import path
from apps.chat.views import (
    get_or_create_ai_session_api,
    add_product_context_api,
    send_ai_message_api,
    escalate_to_seller_api,
    send_direct_message_api,
    get_session_messages_api,
)

app_name = "chat"

urlpatterns = [
    path("chat/api/sessions/ai/", get_or_create_ai_session_api, name="get_or_create_ai_session"),
    path("chat/api/sessions/<uuid:session_id>/products/", add_product_context_api, name="add_product_context"),
    path("chat/api/sessions/<uuid:session_id>/send/", send_ai_message_api, name="send_ai_message"),
    path("chat/api/sessions/<uuid:session_id>/escalate-to-seller/", escalate_to_seller_api, name="escalate_to_seller"),

    # General / Direct Chat Messages
    path("chat/api/sessions/<uuid:session_id>/direct-send/", send_direct_message_api, name="send_direct_message"),
    path("chat/api/sessions/<uuid:session_id>/messages/", get_session_messages_api, name="get_session_messages"),
]
