from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import login, authenticate, get_user_model, logout
from django.contrib import messages
from django.core.mail import send_mail
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import OTPToken, SellerProfile, PaymentMethod
from .forms import LogoForm, PaymentForm, PROVIDERS
from django.utils import timezone
from datetime import timedelta
import logging
from django.db import transaction, IntegrityError
from django.core.validators import EmailValidator
import secrets
from django.db.models import F
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
import json

from .models import OTPToken, SellerProfile

# Create your views here.
User = get_user_model()

logger = logging.getLogger(__name__)
email_validator = EmailValidator()

MAX_PAYMENT_METHODS = 5
MAX_OTP_ATTEMPTS = 5

# API AJAX untuk kirim OTP
@require_POST
def send_otp_api(request):
    # Parse json kalau gagal -> status=400
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success' : False, 'message' : 'Format request tidak valid.'}, status=400)

    # Cek Format harus dict
    if not isinstance(data, dict):
        return JsonResponse({'success' : False, 'message' : 'Format request tidak valid.'}, status=400)
    
    email = (data.get('email') or '').strip().lower()
    if not email:
        return JsonResponse({'success': False, 'message': 'Email wajib diisi!'}, status=400)

    try:
        email_validator(email)
    except ValidationError:
        return JsonResponse({'success' : False, 'message': 'Email tidak valid'},status=400)
    
    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({'success': False, 'message': 'Email sudah terdaftar, silahkan login!'}, status=400)

    last_otp = OTPToken.objects.filter(email=email).order_by('-created_at').first()
    if last_otp and last_otp.created_at > timezone.now() - timedelta(seconds=60):
        return JsonResponse({'success': False, 'message': 'Tunggu 60 detik sebelum meminta OTP lagi.'}, status=429)
    
    token = None
    try:        
        otp_code = OTPToken.generate_otp()
        OTPToken.objects.filter(email=email, is_used=False).update(is_used=True)
       
        token = OTPToken.objects.create(email=email, otp_code=otp_code)

        send_mail(
            subject='Kode OTP Pendaftaran BhumiLestari',
            message=f'Kode OTP Kamu untuk mendaftar di BhumiLestari adalah: {otp_code}. Kode ini berlaku selama 5 menit.',
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
        return JsonResponse({'success': True, 'message': 'Kode OTP telah dikirim ke email kamu.'})
    except Exception:
        logger.exception('Gagal mengirim OTP ke %s', email)
        if token:
            token.delete()
        return JsonResponse({'success': False, 'message': 'Gagal mengirim OTP, coba lagi.'}, status=500)

# view Pendaftaran (SignUp)
def register_view(request):
    if request.method == 'POST':
        role = (request.POST.get('role') or 'buyer').strip()
        full_name = (request.POST.get('full_name') or '').strip()
        store_name = (request.POST.get('store_name') or '').strip()
        username_input = (request.POST.get('username') or '').strip()
        email = (request.POST.get('email') or '').strip().lower()
        otp_code = (request.POST.get('otp_code') or '').strip()
        password = (request.POST.get('password') or '')
        confirm_password = (request.POST.get('confirm_password') or '')

        form_data = {
            'role' : role,
            'full_name' : full_name,
            'store_name' : store_name,
            'username_input' : username_input,
            'email' : email,
        }

        # Validasi role: return HTML
        if role not in dict(User.CHOICE_ROLE):
            messages.error(request, 'Role tidak valid')
            return render(request, 'register.html', {'form_data' : form_data})

        # Field wajib untuk Full Name
        if not full_name:
            messages.error(request, 'Nama Lengkap Wajib di isi!')
            return render(request, 'register.html', {'form_data' : form_data})
        
        # Field wajib tergantung role
        if role == User.ROLE_SELLER:
            username = store_name
            if not store_name:
                messages.error(request, 'Nama toko wajib di isi!')
                return render(request, 'register.html', {'form_data' : form_data})
        else:
            username = username_input
            if not username_input:
                messages.error(request, 'Username Wajib di isi!')
                return render(request, 'register.html', {'form_data' : form_data})

        if User.objects.filter(username__iexact=username).exists():
            messages.error(request, 'Username telah digunakan! Harap gunakan username lain.')
            return render(request, 'register.html', {'form_data' : form_data})

        if User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'Email telah terdaftar! Silahkan Login.')
            return render(request, 'register.html', {'form_data' : form_data})

        if role == User.ROLE_SELLER:
            if SellerProfile.objects.filter(store_name__iexact=store_name).exists():
                messages.error(request, 'Nama toko sudah digunakan! Harap gunakan nama lain.')
                return render(request, 'register.html', {'form_data' : form_data})

        if password != confirm_password:
            messages.error(request, 'Konfirmasi password tidak cocok!')
            return render(request, 'register.html', {'form_data' : form_data})

        try:
            validate_password(password, user=User(username=username, email=email))
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
            return render(request, 'register.html', {'form_data' : form_data})

        otp_obj = OTPToken.objects.filter(email=email).order_by('-created_at').first()

        if not otp_obj or not otp_obj.is_valid():
            messages.error(request, 'Kode OTP salah atau sudah kadaluarsa')
            return render(request, 'register.html', {'form_data' : form_data})

        counted = OTPToken.objects.filter(
            pk=otp_obj.pk, attempts__lt=MAX_OTP_ATTEMPTS).update(attempts=F('attempts')+1
        )
        if not counted:
            messages.error(request, 'Terlalu banyak percobaan. Silahkan minta OTP baru.')
            return render(request, 'register.html', {'form_data': form_data})

        if not secrets.compare_digest(otp_obj.otp_code.encode(), otp_code.encode()):
            messages.error(request, 'Kode OTP salah atau sudah kadaluarsa')
            return render(request, 'register.html', {'form_data': form_data})

        # Buat User baru
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    full_name=full_name,
                    role=role
                )

                # Buat Profil toko jika mendaftar sebagi penjual
                if role == User.ROLE_SELLER:
                    SellerProfile.objects.create(user=user, store_name=store_name)

                # Tandai OTP telah terpakai
                otp_obj.is_used = True
                otp_obj.save()
        except IntegrityError:
            messages.error(request, 'Username, email, atau nama toko sudah digunakan. Silahkan coba lagi.')
            return render(request, 'register.html', {'form_data' : form_data})
        except Exception:
            logger.exception('Gagal membuat akun: role=%s username=%s', role, username)
            messages.error(request, 'Terjadi kesalahan saat mendaftar, coba lagi.')
            return render(request, 'register.html', {'form_data' : form_data})

        # Autologin setelah registrasi sukses
        login(request, user)
        messages.success(request, 'Pendaftaran berhasil! Selamat datang di BhumiLestari.')
        return redirect('dashboard:show_dashboard_home')

    return render(request, 'register.html')

# View Login
def login_view(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        user_obj = User.objects.filter(email__iexact=email).first()
        user = authenticate(request, username=user_obj.email, password=password) if user_obj else None

        if user is None:
            messages.error(request, "Email atau password salah!")
            login_url = reverse('users:login')
            if next_url:
                login_url += '?' + urlencode({'next' : next_url})
            return redirect('users:login')

        # if user.role == 'seller':
        #     messages.warning(request, 'Maaf, halaman penjual sedang dalam maintenance.')
        #     return redirect('users:login')

        login(request, user)

        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('dashboard:show_dashboard_home')
    
    return render(request, 'login.html')

@require_POST
def logout_view(request):
    logout(request)
    return redirect('dashboard:show_dashboard_home')

def mask_email(email):
    local, _, domain = email.partition('@')
    return local[:2] + '*' * max(len(local) - 2, 0) + '@' + domain

@login_required
def account_settings(request):
    user = request.user
    is_seller = user.role == User.ROLE_SELLER

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'profile':
            logo_form = LogoForm(request.POST, request.FILES)
            if not logo_form.is_valid():
                for error in logo_form.errors['logo']:
                    messages.error(request, error)
                return redirect('users:account_settings')
            
            name = request.POST.get('name', '').strip()
            if is_seller:
                profile, _ = SellerProfile.objects.get_or_create(
                    user=user, defaults={'store_name': name or user.username}
                )
                if name:
                    profile.store_name = name
                    profile.save()
            else:
                user.full_name = name
            user.phone = request.POST.get('phone', '').strip()
            user.address = request.POST.get('address', '').strip()

            new_logo = logo_form.cleaned_data['logo']
            if new_logo:
                if user.logo:
                    user.logo.delete(save=False)
                user.logo = new_logo
            user.save()
            messages.success(request, 'Perubahan berhasil disimpan.')

        elif action == 'password':
            old = request.POST.get('old_password', '')
            new = request.POST.get('new_password', '')
            confirm = request.POST.get('confirm_password', '')
            if not user.check_password(old):
                messages.error(request, 'Password lama salah.')
            elif new != confirm:
                messages.error(request, 'Konfirmasi password baru tidak cocok.')
            else:
                try:
                    validate_password(new, user)
                except ValidationError as e:
                    for m in e.messages:
                        messages.error(request, m)
                else:
                    user.set_password(new)
                    user.save()
                    update_session_auth_hash(request, user)  # biar nggak ke-logout
                    messages.success(request, 'Password berhasil diperbarui.')

        elif action == 'add_payment':
            if user.payment_methods.count() >= MAX_PAYMENT_METHODS:
                messages.error(request, f'maksimal {MAX_PAYMENT_METHODS} metode pembayaran.')
            else:
                form = PaymentForm(request.POST)
                if form.is_valid():
                    pm = form.save(commit=False)
                    pm.user = user
                    pm.save()
                    messages.success(request, 'Metode pembayaran ditambahkan')
                else:
                    for errors in form.errors.values():
                        for error in error:
                            messages.error(request, error)

        elif action == 'delete_payment':
            PaymentMethod.objects.filter(
                id=request.POST.get('payment_id'), user=user
            ).delete()
            messages.success(request, 'Metode pembayaran dihapus.')

        elif action == 'delete_account':
            password = request.POST.get('password', '')
            if not user.check_password(password):
                messages.error(request, 'Password salah. Akun tidak dihapus.')
            elif user.is_superuser:
                messages.error(request, 'Akun admin tidak dapat dihapus dari sini.')
            else:
                if user.logo:
                    user.logo.delete(save=False)   # hapus file logo dari storage
                logout(request)
                user.delete()                       # SellerProfile & PaymentMethod ikut terhapus (CASCADE)
                messages.success(request, 'Akun Anda berhasil dihapus.')
                return redirect('dashboard:show_dashboard_home')

        return redirect('users:account_settings') 

    current_name = (
        getattr(getattr(user, 'seller_profile', None), 'store_name', '')
        if is_seller else user.full_name
    )
    return render(request, 'account_settings.html', {
        'is_seller': is_seller,
        'current_name': current_name,
        'masked_email': mask_email(user.email),
        'payment_methods': user.payment_methods.all(),
        'providers': PROVIDERS,
    })