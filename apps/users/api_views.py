"""Endpoint JSON untuk aplikasi mobile (Flutter + pbp_django_auth).

View web di views.py tetap dipakai untuk website; file ini hanya menambah
versi JSON-nya. CSRF di-exempt karena klien mobile tidak punya CSRF token.
Catatan: pbp_django_auth menganggap login berhasil HANYA jika status 200,
jadi setiap kegagalan wajib mengembalikan status selain 200.
"""
import logging
import secrets

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import OTPToken, SellerProfile
from .views import (
    LOGIN_LOCKOUT_SECONDS,
    LOGIN_WINDOW_SECONDS,
    MAX_LOGIN_ATTEMPTS,
    MAX_OTP_ATTEMPTS,
    _login_key,
    send_otp_api,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _error(message, status=400):
    return JsonResponse({'status': False, 'message': message}, status=status)


def _user_data(user):
    store_name = getattr(getattr(user, 'seller_profile', None), 'store_name', None)
    return {
        'id': user.pk,
        'username': user.username,
        'email': user.email,
        'full_name': user.full_name,
        'role': user.role,
        'store_name': store_name,
    }


# Kirim OTP: pakai logika yang sama dengan web, hanya CSRF-nya di-exempt.
# Body harus JSON: {"email": "..."}
send_otp_mobile = csrf_exempt(send_otp_api)


@csrf_exempt
@require_POST
def login_mobile(request):
    email = (request.POST.get('email') or '').strip()
    password = request.POST.get('password') or ''
    remember_me = request.POST.get('remember_me') in ('true', '1', 'on')

    if not email or not password:
        return _error('Email dan password wajib diisi!')

    key = _login_key(request, email)
    if cache.get(key, 0) >= MAX_LOGIN_ATTEMPTS:
        return _error(
            f'Terlalu banyak percobaan login. Coba lagi dalam {LOGIN_LOCKOUT_SECONDS // 60} menit',
            status=429,
        )

    user_obj = User.objects.filter(email__iexact=email).first()
    user = authenticate(request, username=user_obj.email, password=password) if user_obj else None
    if user is None:
        cache.add(key, 0, LOGIN_WINDOW_SECONDS)
        attempts = cache.incr(key)
        if attempts >= MAX_LOGIN_ATTEMPTS:
            cache.set(key, attempts, LOGIN_LOCKOUT_SECONDS)
        return _error('Email atau password salah!', status=401)

    cache.delete(key)
    login(request, user)
    if not remember_me:
        # Sesi berakhir saat browser/app ditutup
        request.session.set_expiry(0)

    return JsonResponse({
        'status': True,
        'message': 'Login berhasil!',
        **_user_data(user),
    })


@csrf_exempt
@require_POST
def register_mobile(request):
    role = (request.POST.get('role') or 'buyer').strip()
    full_name = (request.POST.get('full_name') or '').strip()
    store_name = (request.POST.get('store_name') or '').strip()
    username_input = (request.POST.get('username') or '').strip()
    email = (request.POST.get('email') or '').strip().lower()
    otp_code = (request.POST.get('otp_code') or '').strip()
    password = request.POST.get('password') or ''
    confirm_password = request.POST.get('confirm_password') or ''

    if role not in dict(User.CHOICE_ROLE):
        return _error('Role tidak valid')
    if not full_name:
        return _error('Nama Lengkap Wajib di isi!')

    if role == User.ROLE_SELLER:
        username = store_name
        if not store_name:
            return _error('Nama toko wajib di isi!')
    else:
        username = username_input
        if not username_input:
            return _error('Username Wajib di isi!')

    if not email:
        return _error('Email wajib diisi!')
    if User.objects.filter(username__iexact=username).exists():
        return _error('Username telah digunakan! Harap gunakan username lain.')
    if User.objects.filter(email__iexact=email).exists():
        return _error('Email telah terdaftar! Silahkan Login.')
    if role == User.ROLE_SELLER and SellerProfile.objects.filter(store_name__iexact=store_name).exists():
        return _error('Nama toko sudah digunakan! Harap gunakan nama lain.')
    if password != confirm_password:
        return _error('Konfirmasi password tidak cocok!')

    try:
        validate_password(password, user=User(username=username, email=email))
    except ValidationError as e:
        return _error(' '.join(e.messages))

    otp_obj = OTPToken.objects.filter(email=email).order_by('-created_at').first()
    if not otp_obj or not otp_obj.is_valid():
        return _error('Kode OTP salah atau sudah kadaluarsa')

    counted = OTPToken.objects.filter(
        pk=otp_obj.pk, attempts__lt=MAX_OTP_ATTEMPTS
    ).update(attempts=F('attempts') + 1)
    if not counted:
        return _error('Terlalu banyak percobaan. Silahkan minta OTP baru.', status=429)

    if not secrets.compare_digest(otp_obj.otp_code.encode(), otp_code.encode()):
        return _error('Kode OTP salah atau sudah kadaluarsa')

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
                SellerProfile.objects.create(user=user, store_name=store_name)
            otp_obj.is_used = True
            otp_obj.save()
    except IntegrityError:
        return _error('Username, email, atau nama toko sudah digunakan. Silahkan coba lagi.')
    except Exception:
        logger.exception('Gagal membuat akun (mobile): role=%s username=%s', role, username)
        return _error('Terjadi kesalahan saat mendaftar, coba lagi.', status=500)

    return JsonResponse({
        'status': True,
        'message': 'Pendaftaran berhasil! Silahkan login.',
    }, status=201)


@csrf_exempt
@require_POST
def logout_mobile(request):
    username = request.user.username if request.user.is_authenticated else ''
    logout(request)
    return JsonResponse({
        'status': True,
        'username': username,
        'message': 'Logout berhasil!',
    })
