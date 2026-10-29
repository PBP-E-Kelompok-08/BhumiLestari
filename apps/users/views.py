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
from .forms import LogoForm
import json

from .models import OTPToken, SellerProfile

# Create your views here.
User = get_user_model()

# API AJAX untuk kirim OTP
@require_POST
def send_otp_api(request):
    try:
        data = json.loads(request.body)
        email = (data.get('email') or '').strip().lower()

        if not email:
            return JsonResponse({'success': False, 'message': 'Email wajib diisi!'}, status=400)

        if User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'message': 'Email sudah terdaftar, silahkan login!'}, status=400)

        otp_code = OTPToken.generate_otp()
        OTPToken.objects.create(email=email, otp_code=otp_code)

        send_mail(
            subject='Kode OTP Pendaftaran BhumiLestari',
            message=f'Kode OTP Kamu untuk mendaftar di BhumiLestari adalah: {otp_code}. Kode ini berlaku selama 5 menit.',
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
        return JsonResponse({'success': True, 'message': 'Kode OTP telah dikirim ke email kamu.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': 'Gagal mengirim OTP, coba lagi.'}, status=500)

# view Pendaftaran (SignUp)
def register_view(request):
    if request.method == 'POST':
        role = request.POST.get('role', 'buyer')
        full_name = request.POST.get('full_name')
        store_name = request.POST.get('store_name')
        username_input = request.POST.get('username')
        email = request.POST.get('email')
        otp_code = request.POST.get('otp_code')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        if password != confirm_password:
            messages.error(request, 'Konfirmasi password tidak cocok!')
            return render(request, 'register.html')

        try:
            validate_password(password)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
            return render(request, 'register.html')

        otp_obj = OTPToken.objects.filter(email=email, otp_code=otp_code).last()
        if not otp_obj or not otp_obj.is_valid():
            messages.error(request, 'Kode OTP salah atau sudah kadaluarsa')
            return render(request, 'register.html')

        if role == User.ROLE_SELLER:
            username = email.split('@')[0] + '_seller'
        else:
            username = username_input or email.split('@')[0]

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username telah digunakan, coba yang lain.")
            return render(request, 'register.html')

        # Buat User baru
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                full_name=full_name,
                role=role
            )

            # Buat Profil toko jika mendaftar sebagi penjual
            if role == User.ROLE_SELLER and store_name:
                SellerProfile.objects.create(user=user, store_name=store_name)

            # Tandai OTP telah terpakai
            otp_obj.is_used = True
            otp_obj.save()

            # Autologin setelah registrasi sukses
            login(request, user)
            messages.success(request, 'Pendaftaran berhasil! Selamat datang di BhumiLestari.')
            return redirect('dashboard:show_dashboard_home')
        except Exception:
            messages.error(request, 'Terjadi kesalahan saat mendaftar, coba lagi.')

    return render(request, 'register.html')

# View Login
def login_view(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        user_obj = User.objects.filter(email__iexact=email).first()
        user = authenticate(request, username=user_obj.email, password=password) if user_obj else None

        if user is None:
            messages.error(request, "Email atau password salah!")
            return redirect('users:login')

        # if user.role == 'seller':
        #     messages.warning(request, 'Maaf, halaman penjual sedang dalam maintenance.')
        #     return redirect('users:login')

        login(request, user)
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
            method_type = request.POST.get('method_type')
            provider = request.POST.get('provider', '').strip()
            number = request.POST.get('account_number', '').strip()
            if method_type in dict(PaymentMethod.TYPE_CHOICES) and provider and number.isdigit():
                PaymentMethod.objects.create(
                    user=user, method_type=method_type,
                    provider=provider, account_number=number
                )
                messages.success(request, 'Metode pembayaran ditambahkan.')
            else:
                messages.error(request, 'Lengkapi data metode pembayaran.')

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
    })