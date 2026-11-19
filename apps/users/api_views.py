from datetime import timedelta
import logging
import secrets

from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F, ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import PROVIDERS
from .models import OTPToken, PaymentMethod, SellerProfile
from .serializers import (
    AccountDeleteSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PaymentMethodCreateSerializer,
    PaymentMethodSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    SendOTPSerializer,
    UserProfileSerializer,
)
from .views import (
    LOGIN_LOCKOUT_SECONDS,
    LOGIN_WINDOW_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    MAX_OTP_ATTEMPTS,
    MAX_PAYMENT_METHODS,
    _login_key,
)


User = get_user_model()
logger = logging.getLogger(__name__)


class SendOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        last_otp = (
            OTPToken.objects.filter(email=email)
            .order_by("-created_at")
            .first()
        )
        if last_otp and last_otp.created_at > timezone.now() - timedelta(
            seconds=60
        ):
            return Response(
                {
                    "detail": "Tunggu 60 detik sebelum meminta OTP lagi.",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        token = None
        try:
            otp_code = OTPToken.generate_otp()
            OTPToken.objects.filter(email=email, is_used=False).update(
                is_used=True
            )
            token = OTPToken.objects.create(email=email, otp_code=otp_code)
            send_mail(
                subject="Kode OTP Pendaftaran BhumiLestari",
                message=(
                    f"Kode OTP Kamu untuk mendaftar di BhumiLestari adalah: "
                    f"{otp_code}. Kode ini berlaku selama 5 menit."
                ),
                from_email=None,
                recipient_list=[email],
                fail_silently=False,
            )
            return Response(
                {"detail": "Kode OTP telah dikirim ke email kamu."}
            )
        except Exception:
            logger.exception("Gagal mengirim OTP ke %s", email)
            if token:
                token.delete()
            return Response(
                {"detail": "Gagal mengirim OTP, coba lagi."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RegisterAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        email = data["email"]
        otp_code = data["otp_code"]
        role = data.get("role") or User.ROLE_BUYER
        full_name = data["full_name"]
        username = data["resolved_username"]
        store_name = data["store_name"]
        password = data["password"]

        otp_obj = (
            OTPToken.objects.filter(email=email)
            .order_by("-created_at")
            .first()
        )
        if not otp_obj or not otp_obj.is_valid():
            return Response(
                {"otp_code": ["Kode OTP salah atau sudah kadaluarsa"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        counted = OTPToken.objects.filter(
            pk=otp_obj.pk,
            attempts__lt=MAX_OTP_ATTEMPTS,
        ).update(attempts=F("attempts") + 1)
        if not counted:
            return Response(
                {
                    "detail": "Terlalu banyak percobaan. Silahkan minta OTP baru.",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if not secrets.compare_digest(
            otp_obj.otp_code.encode(),
            otp_code.encode(),
        ):
            return Response(
                {"otp_code": ["Kode OTP salah atau sudah kadaluarsa"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    full_name=full_name,
                    role=role,
                )
                if role == User.ROLE_SELLER:
                    SellerProfile.objects.create(
                        user=user,
                        store_name=store_name,
                    )
                otp_obj.is_used = True
                otp_obj.save(update_fields=["is_used"])
        except IntegrityError:
            return Response(
                {
                    "detail": "Username, email, atau nama toko sudah digunakan. Silahkan coba lagi.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        login(request, user)
        auth_token, _ = Token.objects.get_or_create(user=user)
        user_data = UserProfileSerializer(
            user,
            context={"request": request},
        ).data
        return Response(
            {
                "detail": "Pendaftaran berhasil! Selamat datang di BhumiLestari.",
                "token": auth_token.key,
                "user": user_data,
            },
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        key = _login_key(request, email)
        if cache.get(key, 0) >= MAX_LOGIN_ATTEMPTS:
            return Response(
                {
                    "detail": (
                        f"Terlalu banyak percobaan login. "
                        f"Coba lagi dalam {LOGIN_LOCKOUT_SECONDS // 60} menit"
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user_obj = User.objects.filter(email__iexact=email).first()
        user = (
            authenticate(
                request,
                username=user_obj.email,
                password=password,
            )
            if user_obj
            else None
        )
        if user is None:
            cache.add(key, 0, LOGIN_WINDOW_SECONDS)
            attempts = cache.incr(key)
            if attempts >= MAX_LOGIN_ATTEMPTS:
                cache.set(key, attempts, LOGIN_LOCKOUT_SECONDS)
            return Response(
                {"detail": "Email atau password salah!"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache.delete(key)
        login(request, user)
        auth_token, _ = Token.objects.get_or_create(user=user)
        user_data = UserProfileSerializer(
            user,
            context={"request": request},
        ).data
        return Response(
            {
                "detail": "Login berhasil.",
                "token": auth_token.key,
                "user": user_data,
            }
        )


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        logout(request)
        return Response({"detail": "Berhasil logout."})


class ProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get(self, request):
        serializer = UserProfileSerializer(
            request.user,
            context={"request": request},
        )
        return Response(serializer.data)

    def _update(self, request):
        user = request.user
        is_seller = user.role == User.ROLE_SELLER
        serializer = ProfileUpdateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        name = validated["resolved_name"]
        phone = validated["phone"]
        address = validated["address"]
        new_logo = validated.get("logo")
        old_logo_name = None

        with transaction.atomic():
            if is_seller:
                profile, _ = SellerProfile.objects.get_or_create(
                    user=user,
                    defaults={"store_name": name},
                )
                profile.store_name = name
                profile.save()
            else:
                user.full_name = name

            user.phone = phone
            user.address = address

            if new_logo:
                old_logo_name = user.logo.name if user.logo else None
                user.logo = new_logo
            user.save()

        if old_logo_name:
            default_storage.delete(old_logo_name)

        user.refresh_from_db()
        output_serializer = UserProfileSerializer(
            user,
            context={"request": request},
        )
        return Response(
            {
                "detail": "Perubahan berhasil disimpan.",
                "user": output_serializer.data,
            }
        )

    def patch(self, request):
        return self._update(request)

    def put(self, request):
        return self._update(request)


class PasswordChangeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()
        update_session_auth_hash(request, user)
        return Response({"detail": "Password berhasil diperbarui."})


class PaymentMethodListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        methods = request.user.payment_methods.all()
        serializer = PaymentMethodSerializer(methods, many=True)
        return Response(
            {
                "providers": PROVIDERS,
                "payment_methods": serializer.data,
            }
        )

    def post(self, request):
        if request.user.payment_methods.count() >= MAX_PAYMENT_METHODS:
            return Response(
                {"detail": f"maksimal {MAX_PAYMENT_METHODS} metode pembayaran."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PaymentMethodCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pm = serializer.save(user=request.user)
        output_serializer = PaymentMethodSerializer(pm)
        return Response(
            {
                "detail": "Metode pembayaran ditambahkan",
                "payment_method": output_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class PaymentMethodDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, payment_id):
        pm = get_object_or_404(
            PaymentMethod,
            pk=payment_id,
            user=request.user,
        )
        deleted_id = pm.pk
        pm.delete()
        return Response(
            {
                "detail": "Metode pembayaran dihapus.",
                "deleted_id": deleted_id,
            }
        )


class AccountDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _delete_account(self, request):
        serializer = AccountDeleteSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = request.user

        if user.is_superuser:
            return Response(
                {"detail": "Akun admin tidak dapat dihapus dari sini."},
                status=status.HTTP_403_FORBIDDEN,
            )

        logo_name = user.logo.name if user.logo else None
        try:
            with transaction.atomic():
                Token.objects.filter(user=user).delete()
                user.delete()
        except ProtectedError:
            return Response(
                {"detail": "Akun tidak bisa dihapus karena masih punya data terkait."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if logo_name:
            default_storage.delete(logo_name)
        logout(request)
        return Response({"detail": "Akun Anda berhasil dihapus."})

    def post(self, request):
        return self._delete_account(request)

    def delete(self, request):
        return self._delete_account(request)

