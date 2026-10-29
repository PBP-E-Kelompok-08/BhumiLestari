import io
import json
import os
import shutil
import tempfile
from datetime import timedelta
from unittest import expectedFailure
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import forms as forms_module
from .forms import LogoForm
from .models import OTPToken, PaymentMethod, SellerProfile
from .views import mask_email

User = get_user_model()

STRONG_PASSWORD = "KataSandiKuat123"
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="test_media_")
MIN_LENGTH_VALIDATOR = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def make_image(fmt="PNG", name=None, size=(10, 10)):
    """Bikin file gambar valid di memori."""
    ext = {"PNG": "png", "JPEG": "jpg", "GIF": "gif"}[fmt]
    buf = io.BytesIO()
    Image.new("RGB", size, "green").save(buf, format=fmt)
    return SimpleUploadedFile(
        name or f"logo.{ext}", buf.getvalue(), content_type=f"image/{ext}"
    )


def make_user(email="budi@example.com", username="budi", role=User.ROLE_BUYER,
              password=STRONG_PASSWORD, **extra):
    return User.objects.create_user(
        username=username, email=email, password=password, role=role, **extra
    )


def make_seller(email="toko@example.com", username="TokoHijau",
                store_name="TokoHijau", password=STRONG_PASSWORD):
    user = make_user(email=email, username=username,
                     role=User.ROLE_SELLER, password=password)
    SellerProfile.objects.create(user=user, store_name=store_name)
    return user


def msgs(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class UserModelTests(TestCase):
    def test_default_role_is_buyer(self):
        self.assertEqual(make_user().role, User.ROLE_BUYER)

    def test_str_contains_email_and_role(self):
        self.assertEqual(str(make_user()), "budi@example.com (buyer)")

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_email_must_be_unique(self):
        make_user()
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user(username="lain", email="budi@example.com")


class SellerProfileModelTests(TestCase):
    def test_str_returns_store_name(self):
        self.assertEqual(str(make_seller().seller_profile), "TokoHijau")

    def test_external_id_is_zero_padded(self):
        profile = make_seller().seller_profile
        self.assertEqual(profile.external_id, f"sel-{profile.pk:03d}")
        self.assertRegex(profile.external_id, r"^sel-\d{3,}$")

    def test_store_name_must_be_unique(self):
        make_seller()
        other = make_user(email="lain@example.com", username="lain",
                          role=User.ROLE_SELLER)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SellerProfile.objects.create(user=other, store_name="TokoHijau")

    def test_profile_deleted_with_user(self):
        make_seller().delete()
        self.assertEqual(SellerProfile.objects.count(), 0)


class OTPTokenModelTests(TestCase):
    def test_generate_otp_is_six_digits(self):
        for _ in range(200):
            code = OTPToken.generate_otp()
            self.assertEqual(len(code), 6)
            self.assertTrue(code.isdigit())
            self.assertGreaterEqual(int(code), 100000)

    def test_fresh_token_is_valid(self):
        token = OTPToken.objects.create(email="a@b.com", otp_code="123456")
        self.assertTrue(token.is_valid())

    def test_used_token_is_invalid(self):
        token = OTPToken.objects.create(email="a@b.com", otp_code="123456",
                                        is_used=True)
        self.assertFalse(token.is_valid())

    def test_token_older_than_5_minutes_is_invalid(self):
        token = OTPToken.objects.create(email="a@b.com", otp_code="123456")
        OTPToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - timedelta(minutes=5, seconds=1)
        )
        token.refresh_from_db()
        self.assertFalse(token.is_valid())

    def test_token_just_under_5_minutes_is_valid(self):
        token = OTPToken.objects.create(email="a@b.com", otp_code="123456")
        OTPToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - timedelta(minutes=4, seconds=50)
        )
        token.refresh_from_db()
        self.assertTrue(token.is_valid())


class PaymentMethodModelTests(TestCase):
    def setUp(self):
        self.pm = PaymentMethod.objects.create(
            user=make_user(), method_type="bank",
            provider="BCA", account_number="1234567890",
        )

    def test_masked_number_shows_last_four_digits(self):
        self.assertEqual(self.pm.masked_number(), "•••• 7890")

    def test_str(self):
        self.assertEqual(str(self.pm), "BCA - •••• 7890")

    def test_deleted_with_user(self):
        self.pm.user.delete()
        self.assertEqual(PaymentMethod.objects.count(), 0)


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------
class LogoFormTests(SimpleTestCase):
    def test_empty_logo_is_valid(self):
        self.assertTrue(LogoForm({}, {}).is_valid())

    def test_png_is_valid(self):
        self.assertTrue(LogoForm({}, {"logo": make_image("PNG")}).is_valid())

    def test_jpeg_is_valid(self):
        self.assertTrue(LogoForm({}, {"logo": make_image("JPEG")}).is_valid())

    def test_gif_with_gif_extension_is_rejected(self):
        form = LogoForm({}, {"logo": make_image("GIF")})
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)

    def test_gif_disguised_as_png_is_rejected(self):
        form = LogoForm({}, {"logo": make_image("GIF", name="palsu.png")})
        self.assertFalse(form.is_valid())
        self.assertIn("Logo harus berformat JPG atau PNG", form.errors["logo"])

    def test_non_image_is_rejected(self):
        fake = SimpleUploadedFile("a.png", b"bukan gambar", content_type="image/png")
        self.assertFalse(LogoForm({}, {"logo": fake}).is_valid())

    def test_file_larger_than_limit_is_rejected(self):
        with patch.object(forms_module, "MAX_LOGO_SIZE", 10):
            form = LogoForm({}, {"logo": make_image("PNG")})
            self.assertFalse(form.is_valid())
            self.assertIn("Ukuran logo maksimal 2 MB", form.errors["logo"])

    def test_max_size_constant_is_2mb(self):
        self.assertEqual(forms_module.MAX_LOGO_SIZE, 2 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------
class MaskEmailTests(SimpleTestCase):
    def test_normal_email(self):
        self.assertEqual(mask_email("budi@gmail.com"), "bu**@gmail.com")

    def test_two_char_local_part(self):
        self.assertEqual(mask_email("ab@x.com"), "ab@x.com")

    def test_one_char_local_part(self):
        self.assertEqual(mask_email("a@x.com"), "a@x.com")

    def test_domain_is_preserved(self):
        self.assertTrue(
            mask_email("andi.pratama@kampus.ac.id").endswith("@kampus.ac.id"))


# ---------------------------------------------------------------------------
# Views: send OTP
# ---------------------------------------------------------------------------
class SendOtpApiTests(TestCase):
    def setUp(self):
        self.url = reverse("users:send_otp_api")

    def post(self, payload):
        return self.client.post(self.url, data=json.dumps(payload),
                                content_type="application/json")

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_missing_email_returns_400(self):
        r = self.post({})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["success"])

    def test_blank_email_returns_400(self):
        self.assertEqual(self.post({"email": "   "}).status_code, 400)

    def test_registered_email_returns_400(self):
        make_user(email="budi@example.com")
        r = self.post({"email": "budi@example.com"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OTPToken.objects.count(), 0)

    def test_success_creates_token_and_sends_mail(self):
        r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])
        token = OTPToken.objects.get(email="baru@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["baru@example.com"])
        self.assertIn(token.otp_code, mail.outbox[0].body)

    def test_email_is_stripped_and_lowercased(self):
        self.post({"email": "  Baru@Example.COM "})
        self.assertTrue(OTPToken.objects.filter(email="baru@example.com").exists())

    def test_invalid_json_returns_500(self):
        r = self.client.post(self.url, data="bukan json",
                             content_type="application/json")
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()["success"])

    def test_mail_failure_returns_500(self):
        with patch("apps.users.views.send_mail", side_effect=Exception("SMTP down")):
            r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()["success"])


# ---------------------------------------------------------------------------
# Views: register
# ---------------------------------------------------------------------------
@override_settings(AUTH_PASSWORD_VALIDATORS=MIN_LENGTH_VALIDATOR)
class RegisterViewTests(TestCase):
    def setUp(self):
        self.url = reverse("users:register")
        self.email = "baru@example.com"
        self.otp = OTPToken.objects.create(email=self.email, otp_code="123456")

    def payload(self, **override):
        data = {
            "role": "buyer",
            "full_name": "Budi Santoso",
            "username": "budi",
            "email": self.email,
            "otp_code": "123456",
            "password": STRONG_PASSWORD,
            "confirm_password": STRONG_PASSWORD,
        }
        data.update(override)
        return data

    def assertRegisterFailed(self, response, message_part):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(message_part in m for m in msgs(response)),
                        msgs(response))
        self.assertFalse(User.objects.filter(email=self.email).exists())

    def test_get_renders_form(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "register.html")

    def test_register_buyer_success(self):
        r = self.client.post(self.url, self.payload())
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)
        user = User.objects.get(email=self.email)
        self.assertEqual(user.username, "budi")
        self.assertEqual(user.full_name, "Budi Santoso")
        self.assertEqual(user.role, User.ROLE_BUYER)
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertFalse(SellerProfile.objects.exists())

    def test_register_logs_user_in(self):
        self.client.post(self.url, self.payload())
        self.assertIn("_auth_user_id", self.client.session)

    def test_otp_marked_used_after_register(self):
        self.client.post(self.url, self.payload())
        self.otp.refresh_from_db()
        self.assertTrue(self.otp.is_used)

    def test_register_seller_creates_profile_and_uses_store_name_as_username(self):
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="Toko Hijau", username=""))
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email=self.email)
        self.assertEqual(user.role, User.ROLE_SELLER)
        self.assertEqual(user.username, "Toko Hijau")
        self.assertEqual(user.seller_profile.store_name, "Toko Hijau")

    def test_password_mismatch(self):
        r = self.client.post(self.url, self.payload(confirm_password="beda"))
        self.assertRegisterFailed(r, "Konfirmasi password tidak cocok")

    def test_weak_password(self):
        r = self.client.post(self.url, self.payload(
            password="abc", confirm_password="abc"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email=self.email).exists())
        self.assertTrue(msgs(r))

    def test_wrong_otp(self):
        r = self.client.post(self.url, self.payload(otp_code="000000"))
        self.assertRegisterFailed(r, "Kode OTP salah")

    def test_otp_for_other_email_is_rejected(self):
        r = self.client.post(self.url, self.payload(email="lain@example.com"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="lain@example.com").exists())

    def test_expired_otp(self):
        OTPToken.objects.filter(pk=self.otp.pk).update(
            created_at=timezone.now() - timedelta(minutes=10))
        r = self.client.post(self.url, self.payload())
        self.assertRegisterFailed(r, "Kode OTP salah atau sudah kadaluarsa")

    def test_used_otp_cannot_be_reused(self):
        self.client.post(self.url, self.payload())
        self.client.logout()
        r = self.client.post(self.url, self.payload(
            email=self.email, username="budi2"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.filter(email=self.email).count(), 1)

    def test_duplicate_username_for_buyer(self):
        make_user(email="lama@example.com", username="budi")
        r = self.client.post(self.url, self.payload())
        self.assertRegisterFailed(r, "Username telah digunakan")

    def test_duplicate_store_name_for_seller_is_case_insensitive(self):
        make_seller(store_name="TokoHijau", username="TokoHijau")
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="tokohijau", username=""))
        self.assertRegisterFailed(r, "Username telah digunakan")

    def test_failed_register_does_not_consume_otp(self):
        self.client.post(self.url, self.payload(confirm_password="beda"))
        self.otp.refresh_from_db()
        self.assertFalse(self.otp.is_used)

    def test_already_registered_email_shows_error_not_crash(self):
        make_user(email=self.email, username="lama")
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("kesalahan" in m for m in msgs(r)), msgs(r))


# ---------------------------------------------------------------------------
# Views: login / logout
# ---------------------------------------------------------------------------
class LoginViewTests(TestCase):
    def setUp(self):
        self.url = reverse("users:login")
        self.user = make_user()

    def test_get_renders_form(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "login.html")

    def test_login_success(self):
        r = self.client.post(self.url, {"email": "budi@example.com",
                                        "password": STRONG_PASSWORD})
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_email_is_case_insensitive(self):
        r = self.client.post(self.url, {"email": "  BUDI@Example.com ",
                                        "password": STRONG_PASSWORD})
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)

    def test_wrong_password(self):
        r = self.client.post(self.url, {"email": "budi@example.com",
                                        "password": "salah"})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn("Email atau password salah!", msgs(r))

    def test_unknown_email(self):
        r = self.client.post(self.url, {"email": "gaada@example.com",
                                        "password": STRONG_PASSWORD})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_empty_credentials(self):
        r = self.client.post(self.url, {})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.client.post(self.url, {"email": "budi@example.com",
                                    "password": STRONG_PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_post_logs_out(self):
        r = self.client.post(reverse("users:logout"))
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("users:logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)


# ---------------------------------------------------------------------------
# Views: account settings
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT,
                   AUTH_PASSWORD_VALIDATORS=MIN_LENGTH_VALIDATOR)
class AccountSettingsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.url = reverse("users:account_settings")
        self.buyer = make_user()
        self.client.force_login(self.buyer)

    def post(self, action, **data):
        return self.client.post(self.url, {"action": action, **data})

    # --- akses & GET -------------------------------------------------------
    def test_requires_login(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)

    def test_get_context_for_buyer(self):
        self.buyer.full_name = "Budi Santoso"
        self.buyer.save()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["is_seller"])
        self.assertEqual(r.context["current_name"], "Budi Santoso")
        self.assertEqual(r.context["masked_email"], "bu**@example.com")

    def test_get_context_for_seller(self):
        self.client.force_login(make_seller())
        r = self.client.get(self.url)
        self.assertTrue(r.context["is_seller"])
        self.assertEqual(r.context["current_name"], "TokoHijau")

    def test_get_context_for_seller_without_profile(self):
        seller = make_user(email="s@example.com", username="s",
                           role=User.ROLE_SELLER)
        self.client.force_login(seller)
        self.assertEqual(self.client.get(self.url).context["current_name"], "")

    def test_get_lists_only_own_payment_methods(self):
        PaymentMethod.objects.create(user=self.buyer, method_type="bank",
                                     provider="BCA", account_number="111111")
        other = make_user(email="o@example.com", username="o")
        PaymentMethod.objects.create(user=other, method_type="bank",
                                     provider="BNI", account_number="222222")
        r = self.client.get(self.url)
        self.assertEqual([p.provider for p in r.context["payment_methods"]], ["BCA"])

    # --- profile -----------------------------------------------------------
    def test_update_profile_buyer(self):
        r = self.post("profile", name="Budi Baru", phone="0812",
                      address="Jl. Mawar 1")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Budi Baru")
        self.assertEqual(self.buyer.phone, "0812")
        self.assertEqual(self.buyer.address, "Jl. Mawar 1")
        self.assertIn("Perubahan berhasil disimpan.", msgs(r))

    def test_update_profile_strips_whitespace(self):
        self.post("profile", name="  Budi  ", phone=" 0812 ", address=" Jl. A ")
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Budi")
        self.assertEqual(self.buyer.phone, "0812")
        self.assertEqual(self.buyer.address, "Jl. A")

    def test_update_profile_seller_changes_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="Toko Baru", phone="0812", address="Jl. B")
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "Toko Baru")

    def test_update_profile_seller_blank_name_keeps_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="", phone="0812")
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoHijau")

    def test_update_profile_seller_without_profile_creates_one(self):
        seller = make_user(email="s@example.com", username="s",
                           role=User.ROLE_SELLER)
        self.client.force_login(seller)
        self.post("profile", name="Toko Sementara")
        self.assertEqual(
            SellerProfile.objects.get(user=seller).store_name, "Toko Sementara")

    @expectedFailure  # BUG: store_name duplikat -> IntegrityError (500), belum ditangani di views
    def test_update_profile_seller_duplicate_store_name_shows_error(self):
        make_seller(email="a@example.com", username="a", store_name="TokoA")
        seller = make_seller(email="b@example.com", username="b", store_name="TokoB")
        self.client.force_login(seller)
        r = self.post("profile", name="TokoA")
        self.assertEqual(r.status_code, 302)
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoB")

    def test_upload_valid_logo(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.logo)
        self.assertTrue(self.buyer.logo.name.startswith("logos/"))

    def test_upload_new_logo_deletes_old_file(self):
        self.post("profile", name="Budi", logo=make_image("PNG", name="lama.png"))
        self.buyer.refresh_from_db()
        old_name, old_path = self.buyer.logo.name, self.buyer.logo.path
        self.post("profile", name="Budi", logo=make_image("JPEG", name="baru.jpg"))
        self.buyer.refresh_from_db()
        self.assertNotEqual(self.buyer.logo.name, old_name)
        self.assertFalse(os.path.exists(old_path))

    def test_invalid_logo_shows_error_and_changes_nothing(self):
        r = self.post("profile", name="Nama Baru", logo=make_image("GIF"))
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "")
        self.assertFalse(self.buyer.logo)
        self.assertTrue(msgs(r))

    def test_profile_update_without_logo_keeps_existing_logo(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        logo_name = self.buyer.logo.name
        self.post("profile", name="Budi 2")
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.logo.name, logo_name)

    # --- ganti password ----------------------------------------------------
    def test_change_password_success(self):
        r = self.post("password", old_password=STRONG_PASSWORD,
                      new_password="PasswordBaru456",
                      confirm_password="PasswordBaru456")
        self.assertIn("Password berhasil diperbarui.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password("PasswordBaru456"))

    def test_change_password_keeps_user_logged_in(self):
        self.post("password", old_password=STRONG_PASSWORD,
                  new_password="PasswordBaru456",
                  confirm_password="PasswordBaru456")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_change_password_wrong_old_password(self):
        r = self.post("password", old_password="salah",
                      new_password="PasswordBaru456",
                      confirm_password="PasswordBaru456")
        self.assertIn("Password lama salah.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password(STRONG_PASSWORD))

    def test_change_password_confirmation_mismatch(self):
        r = self.post("password", old_password=STRONG_PASSWORD,
                      new_password="PasswordBaru456",
                      confirm_password="Beda12345678")
        self.assertIn("Konfirmasi password baru tidak cocok.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password(STRONG_PASSWORD))

    def test_change_password_too_weak(self):
        r = self.post("password", old_password=STRONG_PASSWORD,
                      new_password="abc", confirm_password="abc")
        self.assertTrue(msgs(r))
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password(STRONG_PASSWORD))

    # --- metode pembayaran -------------------------------------------------
    def test_add_payment_success(self):
        r = self.post("add_payment", method_type="ewallet",
                      provider=" GoPay ", account_number=" 08123456789 ")
        self.assertIn("Metode pembayaran ditambahkan.", msgs(r))
        pm = PaymentMethod.objects.get(user=self.buyer)
        self.assertEqual(pm.method_type, "ewallet")
        self.assertEqual(pm.provider, "GoPay")
        self.assertEqual(pm.account_number, "08123456789")

    def test_add_payment_invalid_type(self):
        r = self.post("add_payment", method_type="crypto",
                      provider="X", account_number="123")
        self.assertIn("Lengkapi data metode pembayaran.", msgs(r))
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_non_digit_number(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="12ab34")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_empty_provider(self):
        self.post("add_payment", method_type="bank",
                  provider="  ", account_number="1234")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_empty_number(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_delete_own_payment(self):
        pm = PaymentMethod.objects.create(user=self.buyer, method_type="bank",
                                          provider="BCA", account_number="1234")
        r = self.post("delete_payment", payment_id=pm.id)
        self.assertIn("Metode pembayaran dihapus.", msgs(r))
        self.assertFalse(PaymentMethod.objects.filter(pk=pm.pk).exists())

    def test_cannot_delete_other_users_payment(self):
        other = make_user(email="o@example.com", username="o")
        pm = PaymentMethod.objects.create(user=other, method_type="bank",
                                          provider="BCA", account_number="1234")
        self.post("delete_payment", payment_id=pm.id)
        self.assertTrue(PaymentMethod.objects.filter(pk=pm.pk).exists())

    # --- hapus akun --------------------------------------------------------
    def test_delete_account_success(self):
        pm = PaymentMethod.objects.create(user=self.buyer, method_type="bank",
                                          provider="BCA", account_number="1234")
        r = self.post("delete_account", password=STRONG_PASSWORD)
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=self.buyer.pk).exists())
        self.assertFalse(PaymentMethod.objects.filter(pk=pm.pk).exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_delete_seller_account_removes_profile(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("delete_account", password=STRONG_PASSWORD)
        self.assertFalse(SellerProfile.objects.exists())

    def test_delete_account_removes_logo_file(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        path = self.buyer.logo.path
        self.assertTrue(os.path.exists(path))
        self.post("delete_account", password=STRONG_PASSWORD)
        self.assertFalse(os.path.exists(path))

    def test_delete_account_wrong_password(self):
        r = self.post("delete_account", password="salah")
        self.assertIn("Password salah. Akun tidak dihapus.", msgs(r))
        self.assertTrue(User.objects.filter(pk=self.buyer.pk).exists())

    def test_superuser_cannot_delete_account(self):
        admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password=STRONG_PASSWORD)
        self.client.force_login(admin)
        r = self.post("delete_account", password=STRONG_PASSWORD)
        self.assertIn("Akun admin tidak dapat dihapus dari sini.", msgs(r))
        self.assertTrue(User.objects.filter(pk=admin.pk).exists())

    # --- aksi tak dikenal --------------------------------------------------
    def test_unknown_action_just_redirects(self):
        r = self.post("hack")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)