from datetime import datetime
from rest_framework import serializers

from .models import (
    BroadcastChannel,
    BroadcastMessage,
    ChatMessage,
    ChatSession,
    ProductKnowledge,
    SellerChatSettings,
    SessionProductContext,
    SessionRating,
    UserReport,
)
from .views import _format_time_str, _get_seller_store_name


class ProductContextItemSerializer(serializers.Serializer):
    product_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    product_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )


class SessionProductContextSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionProductContext
        fields = ["product_id", "product_name"]


class AISessionCreateSerializer(serializers.Serializer):
    seller_id = serializers.IntegerField(
        error_messages={
            "required": "Parameter seller_id wajib disertakan.",
            "null": "Parameter seller_id wajib disertakan.",
        }
    )
    products = ProductContextItemSerializer(
        many=True,
        required=False,
        default=list,
    )


class ProductContextAddSerializer(serializers.Serializer):
    products = ProductContextItemSerializer(
        many=True,
        required=False,
        default=list,
    )


class MessageContentSerializer(serializers.Serializer):
    content = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "Content pesan tidak boleh kosong.",
            "blank": "Content pesan tidak boleh kosong.",
        },
    )


class ChatMessageSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    sender_email = serializers.SerializerMethodField()
    sender_name = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "sender_type",
            "sender_email",
            "sender_name",
            "content",
            "is_inherited_from_ai",
            "is_read",
            "created_at",
        ]

    def get_id(self, obj):
        return str(obj.id)

    def get_sender_email(self, obj):
        return obj.sender.email if obj.sender else None

    def get_sender_name(self, obj):
        if obj.sender:
            return obj.sender.full_name
        return "AI Assistant" if obj.sender_type == "ai" else "Sistem"

    def get_created_at(self, obj):
        return obj.created_at.isoformat()


class SessionRatingSerializer(serializers.ModelSerializer):
    rating = serializers.IntegerField(
        default=5,
        error_messages={
            "invalid": "Rating harus berupa angka 1 sampai 5.",
        },
    )
    feedback = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    created_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SessionRating
        fields = ["rating", "feedback", "created_at"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError(
                "Rating harus bernilai antara 1 sampai 5."
            )
        return value

    def get_created_at(self, obj):
        return obj.created_at.isoformat() if obj.created_at else None


class UserReportCreateSerializer(serializers.ModelSerializer):
    reported_user_id = serializers.IntegerField(
        error_messages={
            "required": "reported_user_id dan reason wajib diisi.",
            "null": "reported_user_id dan reason wajib diisi.",
        }
    )
    session_id = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "reported_user_id dan reason wajib diisi.",
            "blank": "reported_user_id dan reason wajib diisi.",
        },
    )

    class Meta:
        model = UserReport
        fields = ["reported_user_id", "session_id", "reason"]


class SellerChatSettingsSerializer(serializers.ModelSerializer):
    bot_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    welcome_message = serializers.CharField(required=False, allow_blank=True)
    closed_message = serializers.CharField(required=False, allow_blank=True)
    operating_hours_start = serializers.CharField(required=False)
    operating_hours_end = serializers.CharField(required=False)
    updated_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SellerChatSettings
        fields = [
            "is_auto_reply_enabled",
            "bot_name",
            "welcome_message",
            "operating_hours_start",
            "operating_hours_end",
            "closed_message",
            "updated_at",
        ]

    def validate_bot_name(self, value):
        return (value or "").strip() or "BhumiBot"

    def validate_welcome_message(self, value):
        return (value or "").strip()

    def validate_closed_message(self, value):
        return (value or "").strip()

    def validate_operating_hours_start(self, value):
        try:
            return datetime.strptime(str(value).strip(), "%H:%M").time()
        except ValueError:
            raise serializers.ValidationError(
                "Format operating_hours_start harus HH:MM (contoh 08:00)."
            )

    def validate_operating_hours_end(self, value):
        try:
            return datetime.strptime(str(value).strip(), "%H:%M").time()
        except ValueError:
            raise serializers.ValidationError(
                "Format operating_hours_end harus HH:MM (contoh 19:00)."
            )

    def get_updated_at(self, obj):
        return obj.updated_at.isoformat() if obj.updated_at else None

    def to_representation(self, instance):
        return {
            "is_auto_reply_enabled": instance.is_auto_reply_enabled,
            "bot_name": instance.bot_name,
            "welcome_message": instance.welcome_message,
            "operating_hours_start": _format_time_str(
                instance.operating_hours_start
            ),
            "operating_hours_end": _format_time_str(
                instance.operating_hours_end
            ),
            "closed_message": instance.closed_message,
            "updated_at": self.get_updated_at(instance),
        }


class ProductKnowledgeSerializer(serializers.ModelSerializer):
    product_id = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    product_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    question = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "question dan answer wajib diisi.",
            "blank": "question dan answer wajib diisi.",
        },
    )
    answer = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        error_messages={
            "required": "question dan answer wajib diisi.",
            "blank": "question dan answer wajib diisi.",
        },
    )
    is_active = serializers.BooleanField(required=False, default=True)
    created_at = serializers.SerializerMethodField(read_only=True)
    updated_at = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ProductKnowledge
        fields = [
            "id",
            "product_id",
            "product_name",
            "question",
            "answer",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def validate_product_id(self, value):
        if value in (None, "", "null"):
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def validate_product_name(self, value):
        return str(value or "").strip()

    def get_created_at(self, obj):
        return obj.created_at.isoformat() if obj.created_at else None

    def get_updated_at(self, obj):
        return obj.updated_at.isoformat() if obj.updated_at else None


class BroadcastMessageSerializer(serializers.ModelSerializer):
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = BroadcastMessage
        fields = ["id", "content", "viewed_count", "created_at"]

    def get_created_at(self, obj):
        return obj.created_at.isoformat()


class BroadcastChannelSerializer(serializers.ModelSerializer):
    seller_email = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    is_added = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = BroadcastChannel
        fields = [
            "id",
            "name",
            "description",
            "seller_email",
            "store_name",
            "followers_count",
            "is_archived",
            "is_owner",
            "is_following",
            "is_added",
            "last_message",
        ]

    def get_seller_email(self, obj):
        return obj.seller.email

    def get_store_name(self, obj):
        return _get_seller_store_name(obj.seller)

    def _user(self):
        request = self.context.get("request")
        return request.user if request else None

    def get_is_archived(self, obj):
        user = self._user()
        if not user or not user.is_authenticated:
            return False
        return obj.archived_by.filter(id=user.id).exists()

    def get_is_owner(self, obj):
        user = self._user()
        if not user or not user.is_authenticated:
            return False
        return obj.seller_id == user.id

    def get_is_following(self, obj):
        user = self._user()
        if not user or not user.is_authenticated:
            return False
        return obj.followers.filter(id=user.id).exists()

    def get_is_added(self, obj):
        user = self._user()
        if not user or not user.is_authenticated:
            return False
        return obj.added_by.filter(id=user.id).exists()

    def get_last_message(self, obj):
        last_msg = obj.messages.first() if obj.messages.exists() else None
        return {
            "content": last_msg.content if last_msg else None,
            "created_at": last_msg.created_at.isoformat() if last_msg else None,
        }
