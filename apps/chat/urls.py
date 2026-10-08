from django.urls import path
from apps.chat.views import (
    get_or_create_ai_session_api,
    add_product_context_api,
)

app_name = "chat"

urlpatterns = [
    path("chat/api/sessions/ai/", get_or_create_ai_session_api, name="get_or_create_ai_session"),
    path("chat/api/sessions/<uuid:session_id>/products/", add_product_context_api, name="add_product_context"),
]
