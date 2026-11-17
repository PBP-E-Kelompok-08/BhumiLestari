from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from .forms import ALLOWED_TYPES, PROVIDERS, validasi_logo
from .models import PaymentMethod, SellerProfile
from .views import mask_email


User = get_user_model()


class SellerProfileSerializer(serializers.ModelSerializer):
    external_id = serializers.ReadOnlyField()

    class Meta:
        model = SellerProfile
        fields = ["id", "store_name", "external_id", "created_at"]


class PaymentMethodSerializer(serializers.ModelSerializer):
    masked_number = serializers.SerializerMethodField()

    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "method_type",
            "provider",
            "account_number",
            "masked_number",
            "created_at",
        ]

    def get_masked_number(self, obj):
        return obj.masked_number()


class PaymentMethodCreateSerializer(serializers.ModelSerializer):
    method_type = serializers.ChoiceField(choices=ALLOWED_TYPES)
    provider = serializers.ChoiceField(
        choices=[(p, p) for daftar in PROVIDERS.values() for p in daftar]
    )
    account_number = serializers.CharField(max_length=50)

    class Meta:
        model = PaymentMethod
        fields = ["method_type", "provider", "account_number"]

    def validate_account_number(self, value):
        number = (value or "").strip()
        if not number.isdigit():
            raise serializers.ValidationError("Nomor hanya boleh berisi angka.")
        if not 8 <= len(number) <= 20:
            raise serializers.ValidationError("Nomor harus 8 sampai 20 digit.")
        return number

    def validate(self, attrs):
        tipe = attrs.get("method_type")
        provider = attrs.get("provider")
        if tipe and provider and provider not in PROVIDERS.get(tipe, []):
            raise serializers.ValidationError(
                {"provider": ["Provider tidak sesuai dengan tipe yang dipilih."]}
            )
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    masked_email = serializers.SerializerMethodField()
    is_seller = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()
    current_name = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    seller_profile = SellerProfileSerializer(read_only=True)
    payment_methods = PaymentMethodSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "masked_email",
            "full_name",
            "current_name",
            "role",
            "is_seller",
            "store_name",
            "phone",
            "address",
            "logo_url",
            "seller_profile",
            "payment_methods",
        ]

    def get_masked_email(self, obj):
        return mask_email(obj.email or "")

    def get_is_seller(self, obj):
        return obj.role == User.ROLE_SELLER

    def get_store_name(self, obj):
        profile = getattr(obj, "seller_profile", None)
        return profile.store_name if profile else None

    def get_current_name(self, obj):
        if obj.role == User.ROLE_SELLER:
            profile = getattr(obj, "seller_profile", None)
            return (profile.store_name if profile else "") or obj.username
        return obj.full_name

    def get_logo_url(self, obj):
        if not obj.logo:
            return None
        try:
            url = obj.logo.url
        except Exception:
            return None
        request = self.context.get("request")
        if request is not None and url.startswith("/"):
            return request.build_absolute_uri(url)
        return url


class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        email = (value or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "Email sudah terdaftar, silahkan login!"
            )
        return email


class RegisterSerializer(serializers.Serializer):
    role = serializers.ChoiceField(
        choices=User.CHOICE_ROLE,
        default=User.ROLE_BUYER,
        required=False,
    )
    full_name = serializers.CharField(max_length=150)
    username = serializers.CharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
    )
    store_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_email(self, value):
        email = (value or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError(
                "Email telah terdaftar! Silahkan Login."
            )
        return email

    def validate_full_name(self, value):
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("Nama Lengkap Wajib di isi!")
        return cleaned

    def validate(self, attrs):
        role = attrs.get("role") or User.ROLE_BUYER
        store_name = (attrs.get("store_name") or "").strip()
        username_input = (attrs.get("username") or "").strip()
        email = attrs.get("email", "")
        password = attrs.get("password", "")
        confirm_password = attrs.get("confirm_password", "")

        if role == User.ROLE_SELLER:
            if not store_name:
                raise serializers.ValidationError(
                    {"store_name": ["Nama toko wajib di isi!"]}
                )
            if SellerProfile.objects.filter(store_name__iexact=store_name).exists():
                raise serializers.ValidationError(
                    {"store_name": ["Nama toko sudah digunakan! Harap gunakan nama lain."]}
                )
            resolved_username = store_name
        else:
            if not username_input:
                raise serializers.ValidationError(
                    {"username": ["Username Wajib di isi!"]}
                )
            resolved_username = username_input

        if User.objects.filter(username__iexact=resolved_username).exists():
            raise serializers.ValidationError(
                {"username": ["Username telah digunakan! Harap gunakan username lain."]}
            )

        if password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": ["Konfirmasi password tidak cocok!"]}
            )

        try:
            validate_password(
                password,
                user=User(username=resolved_username, email=email),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})

        attrs["resolved_username"] = resolved_username
        attrs["store_name"] = store_name
        attrs["otp_code"] = (attrs.get("otp_code") or "").strip()
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_email(self, value):
        return (value or "").strip()


class ProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True)
    full_name = serializers.CharField(required=False, allow_blank=True)
    store_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    logo = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"]),
            validasi_logo,
        ],
    )

    def validate(self, attrs):
        user = self.context["request"].user
        is_seller = user.role == User.ROLE_SELLER

        raw_name = attrs.get("name")
        if raw_name is None:
            raw_name = (
                attrs.get("store_name")
                if is_seller and "store_name" in attrs
                else attrs.get("full_name")
            )

        if raw_name is not None:
            name = raw_name.strip()
        else:
            if is_seller:
                profile = getattr(user, "seller_profile", None)
                name = (profile.store_name if profile else "") or user.username
            else:
                name = user.full_name

        max_name = 100 if is_seller else 150
        if not name:
            raise serializers.ValidationError({"name": ["Nama wajib diisi."]})
        if len(name) > max_name:
            raise serializers.ValidationError(
                {"name": [f"Nama maksimal {max_name} karakter."]}
            )

        if (
            is_seller
            and SellerProfile.objects.filter(store_name__iexact=name)
            .exclude(user=user)
            .exists()
        ):
            raise serializers.ValidationError(
                {"name": ["Nama toko sudah dipakai, silahkan pilih nama lain."]}
            )

        phone = attrs.get("phone", user.phone or "").strip()
        if phone:
            digits = phone[1:] if phone.startswith("+") else phone
            if not digits.isdigit() or not 8 <= len(digits) <= 15:
                raise serializers.ValidationError(
                    {
                        "phone": [
                            "Nomor telepon harus 8 sampai 15 digit angka (boleh diawali +)."
                        ]
                    }
                )

        address = attrs.get("address", user.address or "").strip()
        if len(address) > 500:
            raise serializers.ValidationError(
                {"address": ["Alamat maksimal 500 karakter."]}
            )

        attrs["resolved_name"] = name
        attrs["phone"] = phone
        attrs["address"] = address
        return attrs


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Password lama salah.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        new_password = attrs.get("new_password", "")
        confirm_password = attrs.get("confirm_password", "")
        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"confirm_password": ["Konfirmasi password baru tidak cocok."]}
            )
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                {"new_password": list(exc.messages)}
            )
        return attrs


class AccountDeleteSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(
                "Password salah. Akun tidak dihapus."
            )
        return value

