from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import login, authenticate, get_user_model, logout
from django.contrib import messages
from django.core.mail import send_mail
from django.views.decorators.http import require_POST
import json

from .models import OTPToken, SellerProfile

# Create your views here.
User = get_user_model()

# API AJAX untuk kirim OTP
@require_POST
def send_otp_api(request):
    try:
        data = json.loads(request.body)
        email = data.get('email')

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
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

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

        otp_obj = OTPToken.objects.filter(email=email, otp_code=otp_code).last()
        if not otp_obj or not otp_obj.is_valid():
            messages.error(request, 'Kode OTP salah atau sudah kadaluarsa')
            return render(request, 'register.html')

        if role == User.ROLE_SELLER:
            username = email.split('@')[0] + '_seller'
        else:
            username = username_input or email.split('@')[0]

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
            return redirect('users:login')
        except Exception as e:
            messages.error(request, f'Terjadi kesalahan: {str(e)}')

    return render(request, 'register.html')

# View Login
def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(request, username=email, password=password)

        if user is None:
            messages.error(request, "Email atau password salah!")
            return redirect('users:login')

        if user.role == 'seller':
            messages.warning(request, 'Maaf, halaman penjual sedang dalam maintenance.')
            return redirect('users:login')

        login(request, user)
        return redirect('dashboard:show_dashboard_home')
    
    return render(request, 'login.html')

@require_POST
def logout_view(request):
    logout(request)
    return redirect('dashboard:show_dashboard_home')