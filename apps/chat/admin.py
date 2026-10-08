from django.contrib import admin
from apps.chat.models import ProductKnowledge, ChatSession, SessionProductContext, ChatMessage


class SessionProductContextInline(admin.TabularInline):
    model = SessionProductContext
    extra = 0

class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ('sender_type', 'sender', 'content', 'is_inherited_from_ai', 'created_at')
    readonly_fields = ('created_at',)

@admin.register(ProductKnowledge)
class ProductKnowledgeAdmin(admin.ModelAdmin):
    list_display = ('question', 'product_name', 'product_id', 'seller', 'is_active', 'updated_at')
    list_filter = ('is_active', 'seller')
    search_fields = ('question', 'answer', 'product_id', 'product_name')

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'buyer', 'seller', 'session_type', 'status', 'handover_reason', 'created_at')
    list_filter = ('session_type', 'status', 'handover_reason')
    search_fields = ('id', 'buyer__email', 'seller__email')
    inlines = [SessionProductContextInline, ChatMessageInline]

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'sender_type', 'sender', 'is_inherited_from_ai', 'created_at')
    list_filter = ('sender_type', 'is_inherited_from_ai')
    search_fields = ('content', 'session__id')