import io
import json
import os
import shutil
import tempfile
import time
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import forms as forms_module
from .forms import ALLOWED_TYPES, LogoForm, PaymentForm, PROVIDERS
from .models import OTPToken, PaymentMethod, SellerProfile
from .views import (LOGIN_LOCKOUT_SECONDS, LOGIN_WINDOW_SECONDS,
                    MAX_LOGIN_ATTEMPTS, MAX_OTP_ATTEMPTS,
                    MAX_PAYMENT_METHODS, mask_email)

User = get_user_model()

STRONG_PASSWORD = "KataSandiKuat123"
TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="test_media_")
MIN_LENGTH_VALIDATOR = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]


BANK = PROVIDERS["bank"][0]
EWALLET = PROVIDERS["ewallet"][0]

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

    def test_unused_profile_fields_are_gone(self):
        names = {f.name for f in User._meta.get_fields()}
        self.assertNotIn("bio", names)
        self.assertNotIn("birth_date", names)

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

    def test_attempts_default_to_zero(self):
        token = OTPToken.objects.create(email="a@b.com", otp_code="123456")
        self.assertEqual(token.attempts, 0)

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
# Forms: PaymentForm
# ---------------------------------------------------------------------------
class PaymentFormTests(TestCase):
    def form(self, **override):
        data = {"method_type": "bank", "provider": "BCA",
                "account_number": "1234567890"}
        data.update(override)
        return PaymentForm(data)

    def test_valid_bank(self):
        self.assertTrue(self.form().is_valid())

    def test_valid_ewallet(self):
        self.assertTrue(self.form(method_type="ewallet", provider=EWALLET,
                                  account_number="081234567890").is_valid())

    def test_qris_type_is_rejected(self):
        form = self.form(method_type="qris")
        self.assertFalse(form.is_valid())
        self.assertIn("method_type", form.errors)

    def test_unknown_type_is_rejected(self):
        self.assertFalse(self.form(method_type="crypto").is_valid())

    def test_provider_not_in_whitelist_is_rejected(self):
        form = self.form(provider="BankAbalAbal")
        self.assertFalse(form.is_valid())
        self.assertIn("provider", form.errors)

    def test_provider_must_match_type(self):
        form = self.form(method_type="bank", provider=EWALLET)
        self.assertFalse(form.is_valid())
        self.assertIn("provider", form.errors)

    def test_ewallet_provider_with_bank_type_reverse_case(self):
        self.assertFalse(self.form(method_type="ewallet", provider="BCA").is_valid())

    def test_every_listed_provider_is_valid_for_its_type(self):
        for tipe, daftar in PROVIDERS.items():
            for provider in daftar:
                with self.subTest(tipe=tipe, provider=provider):
                    self.assertTrue(
                        self.form(method_type=tipe, provider=provider).is_valid())

    def test_number_must_be_digits(self):
        form = self.form(account_number="12ab34567890")
        self.assertFalse(form.is_valid())
        self.assertIn("account_number", form.errors)

    def test_number_with_spaces_or_dashes_is_rejected(self):
        self.assertFalse(self.form(account_number="1234 5678").is_valid())
        self.assertFalse(self.form(account_number="1234-5678").is_valid())

    def test_number_length_boundaries(self):
        self.assertFalse(self.form(account_number="1234567").is_valid())       # 7
        self.assertTrue(self.form(account_number="12345678").is_valid())       # 8
        self.assertTrue(self.form(account_number="1" * 20).is_valid())         # 20
        self.assertFalse(self.form(account_number="1" * 21).is_valid())        # 21

    def test_number_is_stripped(self):
        form = self.form(account_number="  12345678  ")
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["account_number"], "12345678")

    def test_required_fields(self):
        form = PaymentForm({})
        self.assertFalse(form.is_valid())
        for field in ("method_type", "provider", "account_number"):
            self.assertIn(field, form.errors)

    def test_user_is_not_a_form_field(self):
        self.assertNotIn("user", PaymentForm().fields)

    def test_constants_are_consistent(self):
        self.assertEqual({t for t, _ in ALLOWED_TYPES}, set(PROVIDERS))
        self.assertNotIn("qris", PROVIDERS)


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

    def test_null_email_returns_400(self):
        self.assertEqual(self.post({"email": None}).status_code, 400)

    def test_invalid_email_format_returns_400(self):
        for bad in ("bukan-email", "a@", "@b.com", "a b@c.com", "a@b"):
            with self.subTest(email=bad):
                r = self.post({"email": bad})
                self.assertEqual(r.status_code, 400)
                self.assertFalse(r.json()["success"])
        self.assertEqual(OTPToken.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_registered_email_returns_400(self):
        make_user(email="budi@example.com")
        r = self.post({"email": "budi@example.com"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OTPToken.objects.count(), 0)

    def test_registered_email_check_is_case_insensitive(self):
        make_user(email="budi@example.com")
        r = self.post({"email": "BUDI@Example.com"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(OTPToken.objects.count(), 0)

    def test_success_creates_token_and_sends_mail(self):
        r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])
        token = OTPToken.objects.get(email="baru@example.com")
        self.assertEqual(token.attempts, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["baru@example.com"])
        self.assertIn(token.otp_code, mail.outbox[0].body)

    def test_email_is_stripped_and_lowercased(self):
        self.post({"email": "  Baru@Example.COM "})
        self.assertTrue(OTPToken.objects.filter(email="baru@example.com").exists())

    def test_invalid_json_returns_400(self):
        r = self.client.post(self.url, data="bukan json",
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["success"])

    def test_json_that_is_not_an_object_returns_400(self):
        for body in ("[1, 2]", '"teks"', "123", "null"):
            with self.subTest(body=body):
                r = self.client.post(self.url, data=body,
                                     content_type="application/json")
                self.assertEqual(r.status_code, 400)
                self.assertFalse(r.json()["success"])

    # --- gagal kirim email -------------------------------------------------
    def test_mail_failure_returns_500(self):
        with patch("apps.users.views.send_mail", side_effect=Exception("SMTP down")):
            r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()["success"])

    def test_mail_failure_removes_the_new_token(self):
        with patch("apps.users.views.send_mail", side_effect=Exception("SMTP down")):
            self.post({"email": "baru@example.com"})
        self.assertEqual(OTPToken.objects.count(), 0)

    def test_mail_failure_is_logged(self):
        with patch("apps.users.views.send_mail", side_effect=Exception("SMTP down")):
            with self.assertLogs("apps.users.views", level="ERROR"):
                self.post({"email": "baru@example.com"})

    def test_can_retry_immediately_after_mail_failure(self):
        with patch("apps.users.views.send_mail", side_effect=Exception("SMTP down")):
            self.post({"email": "baru@example.com"})
        r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 200)

    def test_failure_before_token_exists_is_handled(self):
        with patch.object(OTPToken, "generate_otp", side_effect=Exception("boom")):
            r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()["success"])

    # --- cooldown ----------------------------------------------------------
    def test_second_request_within_60_seconds_returns_429(self):
        self.assertEqual(self.post({"email": "baru@example.com"}).status_code, 200)
        r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 429)
        self.assertFalse(r.json()["success"])
        self.assertEqual(OTPToken.objects.filter(email="baru@example.com").count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_cooldown_is_per_email(self):
        self.post({"email": "a@example.com"})
        r = self.post({"email": "b@example.com"})
        self.assertEqual(r.status_code, 200)

    def test_cooldown_ignores_email_case_and_spaces(self):
        self.post({"email": "baru@example.com"})
        r = self.post({"email": "  BARU@example.com "})
        self.assertEqual(r.status_code, 429)

    def test_request_allowed_again_after_cooldown(self):
        self.post({"email": "baru@example.com"})
        OTPToken.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        r = self.post({"email": "baru@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(mail.outbox), 2)

    def test_request_still_blocked_just_before_cooldown_ends(self):
        self.post({"email": "baru@example.com"})
        OTPToken.objects.update(created_at=timezone.now() - timedelta(seconds=55))
        self.assertEqual(self.post({"email": "baru@example.com"}).status_code, 429)

    def test_cooldown_checked_before_sending_mail(self):
        self.post({"email": "baru@example.com"})
        with patch("apps.users.views.send_mail") as fake_send:
            self.post({"email": "baru@example.com"})
        fake_send.assert_not_called()

    # --- OTP lama dimatikan ------------------------------------------------
    def test_new_otp_invalidates_previous_unused_otp(self):
        self.post({"email": "baru@example.com"})
        OTPToken.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        old = OTPToken.objects.get(email="baru@example.com")
        self.post({"email": "baru@example.com"})
        old.refresh_from_db()
        self.assertTrue(old.is_used)
        self.assertEqual(
            OTPToken.objects.filter(email="baru@example.com", is_used=False).count(), 1)

    def test_new_otp_does_not_touch_other_emails(self):
        other = OTPToken.objects.create(email="lain@example.com", otp_code="111111")
        self.post({"email": "baru@example.com"})
        other.refresh_from_db()
        self.assertFalse(other.is_used)


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

    # --- dasar -------------------------------------------------------------
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

    def test_inputs_are_normalized(self):
        r = self.client.post(self.url, self.payload(
            email="  BARU@Example.com ", full_name="  Budi  ",
            username="  budi  ", otp_code=" 123456 "))
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(email=self.email)
        self.assertEqual(user.full_name, "Budi")
        self.assertEqual(user.username, "budi")

    # --- role --------------------------------------------------------------
    def test_invalid_role_is_rejected(self):
        r = self.client.post(self.url, self.payload(role="admin"))
        self.assertRegisterFailed(r, "Role tidak valid")

    def test_cannot_register_as_superuser_via_role(self):
        self.client.post(self.url, self.payload(role="superuser"))
        self.assertFalse(User.objects.filter(is_superuser=True).exists())

    def test_missing_role_defaults_to_buyer(self):
        data = self.payload()
        del data["role"]
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(User.objects.get(email=self.email).role, User.ROLE_BUYER)

    # --- field wajib -------------------------------------------------------
    def test_full_name_is_required(self):
        r = self.client.post(self.url, self.payload(full_name=""))
        self.assertRegisterFailed(r, "Nama Lengkap")

    def test_full_name_of_only_spaces_is_rejected(self):
        r = self.client.post(self.url, self.payload(full_name="    "))
        self.assertRegisterFailed(r, "Nama Lengkap")

    def test_full_name_is_required_for_seller_too(self):
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="Toko Hijau", username="", full_name=""))
        self.assertRegisterFailed(r, "Nama Lengkap")
        self.assertFalse(SellerProfile.objects.exists())

    def test_buyer_username_is_required(self):
        r = self.client.post(self.url, self.payload(username=""))
        self.assertRegisterFailed(r, "Username")

    def test_seller_store_name_is_required(self):
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="   ", username=""))
        self.assertRegisterFailed(r, "Nama toko")

    def test_missing_password_fields_do_not_crash(self):
        data = self.payload()
        del data["password"]
        del data["confirm_password"]
        r = self.client.post(self.url, data)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email=self.email).exists())

    def test_missing_every_field_does_not_crash(self):
        r = self.client.post(self.url, {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    # --- password ----------------------------------------------------------
    def test_password_mismatch(self):
        r = self.client.post(self.url, self.payload(confirm_password="beda"))
        self.assertRegisterFailed(r, "Konfirmasi password tidak cocok")

    def test_password_is_not_stripped(self):
        pw = "  " + STRONG_PASSWORD + "  "
        r = self.client.post(self.url, self.payload(password=pw, confirm_password=pw))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.get(email=self.email).check_password(pw))

    def test_weak_password(self):
        r = self.client.post(self.url, self.payload(
            password="abc", confirm_password="abc"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email=self.email).exists())
        self.assertTrue(msgs(r))

    # --- OTP ---------------------------------------------------------------
    def test_wrong_otp(self):
        r = self.client.post(self.url, self.payload(otp_code="000000"))
        self.assertRegisterFailed(r, "Kode OTP salah")

    def test_empty_otp(self):
        r = self.client.post(self.url, self.payload(otp_code=""))
        self.assertRegisterFailed(r, "Kode OTP salah")

    def test_non_ascii_otp_does_not_crash(self):
        r = self.client.post(self.url, self.payload(otp_code="１２３４５６"))
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

    def test_only_latest_otp_is_accepted(self):
        OTPToken.objects.filter(pk=self.otp.pk).update(
            created_at=timezone.now() - timedelta(minutes=1))
        OTPToken.objects.create(email=self.email, otp_code="654321")
        r = self.client.post(self.url, self.payload(otp_code="123456"))
        self.assertRegisterFailed(r, "Kode OTP salah")
        r = self.client.post(self.url, self.payload(otp_code="654321"))
        self.assertEqual(r.status_code, 302)

    def test_failed_register_does_not_consume_otp(self):
        self.client.post(self.url, self.payload(confirm_password="beda"))
        self.otp.refresh_from_db()
        self.assertFalse(self.otp.is_used)

    # --- batas percobaan OTP ----------------------------------------------
    def test_wrong_otp_increments_attempts(self):
        self.client.post(self.url, self.payload(otp_code="000000"))
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.attempts, 1)
        self.client.post(self.url, self.payload(otp_code="111111"))
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.attempts, 2)

    def test_validation_errors_before_otp_do_not_use_attempts(self):
        self.client.post(self.url, self.payload(confirm_password="beda"))
        self.client.post(self.url, self.payload(username=""))
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.attempts, 0)

    def test_correct_otp_on_last_allowed_attempt_succeeds(self):
        for _ in range(MAX_OTP_ATTEMPTS - 1):
            self.client.post(self.url, self.payload(otp_code="000000"))
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(email=self.email).exists())

    def test_otp_is_locked_after_max_wrong_attempts(self):
        for _ in range(MAX_OTP_ATTEMPTS):
            self.client.post(self.url, self.payload(otp_code="000000"))
        r = self.client.post(self.url, self.payload())   # kode benar, tapi sudah terkunci
        self.assertRegisterFailed(r, "Terlalu banyak percobaan")

    def test_attempts_never_exceed_the_limit(self):
        for _ in range(MAX_OTP_ATTEMPTS + 3):
            self.client.post(self.url, self.payload(otp_code="000000"))
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.attempts, MAX_OTP_ATTEMPTS)

    def test_new_otp_starts_with_fresh_attempts(self):
        OTPToken.objects.filter(pk=self.otp.pk).update(attempts=MAX_OTP_ATTEMPTS)
        OTPToken.objects.filter(pk=self.otp.pk).update(
            created_at=timezone.now() - timedelta(minutes=1))
        OTPToken.objects.create(email=self.email, otp_code="654321")
        r = self.client.post(self.url, self.payload(otp_code="654321"))
        self.assertEqual(r.status_code, 302)

    def test_lock_on_one_email_does_not_affect_another(self):
        OTPToken.objects.filter(pk=self.otp.pk).update(attempts=MAX_OTP_ATTEMPTS)
        OTPToken.objects.create(email="lain@example.com", otp_code="222222")
        r = self.client.post(self.url, self.payload(
            email="lain@example.com", otp_code="222222"))
        self.assertEqual(r.status_code, 302)

    # --- duplikat ----------------------------------------------------------
    def test_duplicate_username_for_buyer(self):
        make_user(email="lama@example.com", username="budi")
        r = self.client.post(self.url, self.payload())
        self.assertRegisterFailed(r, "Username telah digunakan")

    def test_duplicate_username_is_case_insensitive(self):
        make_user(email="lama@example.com", username="Budi")
        r = self.client.post(self.url, self.payload(username="BUDI"))
        self.assertRegisterFailed(r, "Username telah digunakan")

    def test_duplicate_store_name_for_seller_is_case_insensitive(self):
        make_seller(store_name="TokoHijau", username="TokoHijau")
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="tokohijau", username=""))
        self.assertRegisterFailed(r, "Username telah digunakan")

    def test_duplicate_store_name_with_different_username_is_rejected(self):
        make_seller(store_name="TokoHijau", username="penjual-lama")
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="tokohijau", username=""))
        self.assertRegisterFailed(r, "Nama toko sudah digunakan")

    def test_already_registered_email_shows_error_not_crash(self):
        make_user(email=self.email, username="lama")
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("Email telah terdaftar" in m for m in msgs(r)), msgs(r))

    # --- atomic & error handling ------------------------------------------
    def test_seller_profile_failure_rolls_back_user_and_keeps_otp(self):
        with patch.object(SellerProfile.objects, "create",
                          side_effect=Exception("boom")):
            r = self.client.post(self.url, self.payload(
                role="seller", store_name="Toko Hijau", username=""))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("kesalahan" in m for m in msgs(r)), msgs(r))
        self.assertFalse(User.objects.filter(email=self.email).exists())
        self.otp.refresh_from_db()
        self.assertFalse(self.otp.is_used)

    def test_unexpected_error_is_logged(self):
        with patch.object(User.objects, "create_user", side_effect=Exception("boom")):
            with self.assertLogs("apps.users.views", level="ERROR"):
                r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 200)

    def test_integrity_error_shows_friendly_message(self):
        with patch.object(User.objects, "create_user", side_effect=IntegrityError):
            r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any("sudah digunakan" in m for m in msgs(r)), msgs(r))
        self.assertFalse(User.objects.filter(email=self.email).exists())

    # --- data form dikirim balik ------------------------------------------
    def test_form_data_is_returned_on_error(self):
        r = self.client.post(self.url, self.payload(
            role="seller", store_name="Toko Hijau", username="",
            confirm_password="beda"))
        form_data = r.context["form_data"]
        self.assertEqual(form_data["role"], "seller")
        self.assertEqual(form_data["full_name"], "Budi Santoso")
        self.assertEqual(form_data["store_name"], "Toko Hijau")
        self.assertEqual(form_data["email"], self.email)

    def test_form_data_keeps_buyer_role_and_username(self):
        r = self.client.post(self.url, self.payload(confirm_password="beda"))
        self.assertEqual(r.context["form_data"]["role"], "buyer")
        self.assertEqual(r.context["form_data"]["username_input"], "budi")

    def test_form_data_never_contains_password_or_otp(self):
        r = self.client.post(self.url, self.payload(confirm_password="beda"))
        form_data = r.context["form_data"]
        for key in ("password", "confirm_password", "otp_code"):
            self.assertNotIn(key, form_data)
        self.assertNotIn(STRONG_PASSWORD, str(form_data))
        self.assertNotIn("123456", str(form_data))

    def test_form_data_is_returned_for_every_validation_error(self):
        cases = [
            self.payload(role="admin"),
            self.payload(full_name=""),
            self.payload(username=""),
            self.payload(otp_code="000000"),
            self.payload(password="abc", confirm_password="abc"),
        ]
        for data in cases:
            with self.subTest(data=data):
                r = self.client.post(self.url, data)
                self.assertIn("form_data", r.context)

    def test_get_has_no_form_data(self):
        r = self.client.get(self.url)
        self.assertNotIn("form_data", r.context)


# ---------------------------------------------------------------------------
# Views: login / logout
# ---------------------------------------------------------------------------
class LoginViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("users:login")
        self.user = make_user()

    def login(self, email="budi@example.com", password=STRONG_PASSWORD, **extra):
        return self.client.post(self.url, {"email": email, "password": password},
                                **extra)

    def test_get_renders_form(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "login.html")

    def test_login_success(self):
        r = self.login()
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_email_is_case_insensitive(self):
        r = self.login(email="  BUDI@Example.com ")
        self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                             fetch_redirect_response=False)

    def test_wrong_password(self):
        r = self.login(password="salah")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertIn("Email atau password salah!", msgs(r))

    def test_unknown_email(self):
        r = self.login(email="gaada@example.com")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_error_message_is_the_same_for_unknown_email_and_wrong_password(self):
        a = set(msgs(self.login(password="salah")))
        b = set(msgs(self.login(email="gaada@example.com")))
        self.assertEqual(a, b)
        self.assertEqual(a, {"Email atau password salah!"})

    def test_empty_credentials(self):
        r = self.client.post(self.url, {})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.login()
        self.assertNotIn("_auth_user_id", self.client.session)

    # --- ?next= -------------------------------------------------------------
    def test_get_passes_next_to_template(self):
        r = self.client.get(self.url, {"next": "/users/settings/"})
        self.assertEqual(r.context["next"], "/users/settings/")

    def test_get_without_next_has_empty_next(self):
        self.assertEqual(self.client.get(self.url).context["next"], "")

    def test_login_redirects_to_next_from_form(self):
        r = self.client.post(self.url, {"email": "budi@example.com",
                                        "password": STRONG_PASSWORD,
                                        "next": "/users/settings/"})
        self.assertRedirects(r, "/users/settings/", fetch_redirect_response=False)

    def test_login_redirects_to_next_from_query_string(self):
        r = self.client.post(self.url + "?next=/users/settings/",
                             {"email": "budi@example.com",
                              "password": STRONG_PASSWORD})
        self.assertRedirects(r, "/users/settings/", fetch_redirect_response=False)

    def test_external_next_is_ignored(self):
        for evil in ("https://evil.com/", "//evil.com/", "http://evil.com",
                     "javascript:alert(1)"):
            with self.subTest(next=evil):
                self.client.logout()
                r = self.client.post(self.url, {"email": "budi@example.com",
                                                "password": STRONG_PASSWORD,
                                                "next": evil})
                self.assertRedirects(r, reverse("dashboard:show_dashboard_home"),
                                     fetch_redirect_response=False)

    def test_failed_login_keeps_next(self):
        r = self.client.post(self.url, {"email": "budi@example.com",
                                        "password": "salah",
                                        "next": "/users/settings/"})
        self.assertRedirects(
            r, self.url + "?next=%2Fusers%2Fsettings%2F",
            fetch_redirect_response=False)

    def test_failed_login_without_next_has_clean_redirect(self):
        r = self.login(password="salah")
        self.assertEqual(r.url, self.url)

    def test_login_required_redirect_roundtrip(self):
        r = self.client.get(reverse("users:account_settings"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, self.url + "?next=/users/settings/")
        r = self.client.post(r.url, {"email": "budi@example.com",
                                     "password": STRONG_PASSWORD,
                                     "next": "/users/settings/"})
        self.assertRedirects(r, "/users/settings/", fetch_redirect_response=False)


class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse("users:login")
        self.user = make_user()

    def attempt(self, email="budi@example.com", password="salah", **extra):
        return self.client.post(self.url, {"email": email, "password": password},
                                **extra)

    def fail(self, times, **kwargs):
        for _ in range(times):
            self.attempt(**kwargs)

    def logged_in(self):
        return "_auth_user_id" in self.client.session

    def test_four_failures_do_not_block(self):
        self.fail(MAX_LOGIN_ATTEMPTS - 1)
        self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_max_failures_block_even_the_correct_password(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        r = self.attempt(password=STRONG_PASSWORD)
        self.assertFalse(self.logged_in())
        self.assertTrue(any("Terlalu banyak percobaan login" in m for m in msgs(r)),
                        msgs(r))

    def test_block_message_mentions_lockout_minutes(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        r = self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(
            any(str(LOGIN_LOCKOUT_SECONDS // 60) in m for m in msgs(r)), msgs(r))

    def test_blocked_attempts_redirect_back_to_login(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        r = self.attempt(password=STRONG_PASSWORD)
        self.assertRedirects(r, self.url, fetch_redirect_response=False)

    def test_successful_login_resets_counter(self):
        self.fail(MAX_LOGIN_ATTEMPTS - 1)
        self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())
        self.client.post(reverse("users:logout"))
        self.fail(MAX_LOGIN_ATTEMPTS - 1)
        self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_lockout_is_per_email(self):
        make_user(email="siti@example.com", username="siti")
        self.fail(MAX_LOGIN_ATTEMPTS)
        self.attempt(email="siti@example.com", password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_lockout_email_matching_ignores_case_and_spaces(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        self.attempt(email="  BUDI@example.com ", password=STRONG_PASSWORD)
        self.assertFalse(self.logged_in())

    def test_lockout_is_per_ip(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        self.attempt(password=STRONG_PASSWORD, REMOTE_ADDR="10.9.8.7")
        self.assertTrue(self.logged_in())

    def test_unknown_email_failures_are_counted_too(self):
        self.fail(MAX_LOGIN_ATTEMPTS, email="gaada@example.com",
                  password=STRONG_PASSWORD)
        r = self.attempt(email="gaada@example.com", password=STRONG_PASSWORD)
        self.assertTrue(any("Terlalu banyak percobaan login" in m for m in msgs(r)),
                        msgs(r))

    def test_block_does_not_get_longer_while_blocked(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        start = time.time()
        with patch("time.time", return_value=start + LOGIN_LOCKOUT_SECONDS - 10):
            self.attempt(password=STRONG_PASSWORD)       # masih diblokir, jangan memperpanjang
        with patch("time.time", return_value=start + LOGIN_LOCKOUT_SECONDS + 5):
            self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_block_ends_after_lockout_period(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        with patch("time.time", return_value=time.time() + LOGIN_LOCKOUT_SECONDS + 5):
            self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_block_still_active_before_lockout_period_ends(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        with patch("time.time", return_value=time.time() + LOGIN_LOCKOUT_SECONDS - 30):
            self.attempt(password=STRONG_PASSWORD)
        self.assertFalse(self.logged_in())

    def test_lockout_is_shorter_than_counting_window(self):
        self.assertLess(LOGIN_LOCKOUT_SECONDS, LOGIN_WINDOW_SECONDS)

    def test_failures_outside_window_are_forgotten(self):
        self.fail(MAX_LOGIN_ATTEMPTS - 1)
        later = time.time() + LOGIN_WINDOW_SECONDS + 5
        with patch("time.time", return_value=later):
            self.attempt()                                # hitungan mulai dari 1 lagi
            self.attempt(password=STRONG_PASSWORD)
        self.assertTrue(self.logged_in())

    def test_block_keeps_next_in_redirect(self):
        self.fail(MAX_LOGIN_ATTEMPTS)
        r = self.client.post(self.url, {"email": "budi@example.com",
                                        "password": STRONG_PASSWORD,
                                        "next": "/users/settings/"})
        self.assertRedirects(
            r, self.url + "?next=%2Fusers%2Fsettings%2F",
            fetch_redirect_response=False)


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

    def add_payment(self, user, n, **extra):
        return PaymentMethod.objects.create(
            user=user, method_type="bank", provider="BCA",
            account_number=f"{10000000 + n}", **extra)

    # --- akses & GET -------------------------------------------------------
    def test_requires_login(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)

    def test_post_requires_login(self):
        self.client.logout()
        r = self.post("delete_account", password=STRONG_PASSWORD)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.buyer.pk).exists())

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

    def test_get_context_for_seller_without_profile_falls_back_to_username(self):
        seller = make_user(email="s@example.com", username="s",
                           role=User.ROLE_SELLER)
        self.client.force_login(seller)
        self.assertEqual(self.client.get(self.url).context["current_name"], "s")

    def test_get_context_for_buyer_ignores_username_fallback(self):
        r = self.client.get(self.url)       # full_name kosong, bukan seller
        self.assertEqual(r.context["current_name"], "")

    def test_get_context_contains_providers(self):
        r = self.client.get(self.url)
        self.assertEqual(r.context["providers"], PROVIDERS)

    def test_get_lists_only_own_payment_methods(self):
        PaymentMethod.objects.create(user=self.buyer, method_type="bank",
                                     provider="BCA", account_number="111111")
        other = make_user(email="o@example.com", username="o")
        PaymentMethod.objects.create(user=other, method_type="bank",
                                     provider="BNI", account_number="222222")
        r = self.client.get(self.url)
        self.assertEqual([p.provider for p in r.context["payment_methods"]], ["BCA"])

    # --- profile: berhasil -------------------------------------------------
    def test_update_profile_buyer(self):
        r = self.post("profile", name="Budi Baru", phone="081234567890",
                      address="Jl. Mawar 1")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Budi Baru")
        self.assertEqual(self.buyer.phone, "081234567890")
        self.assertEqual(self.buyer.address, "Jl. Mawar 1")
        self.assertIn("Perubahan berhasil disimpan.", msgs(r))

    def test_update_profile_strips_whitespace(self):
        self.post("profile", name="  Budi  ", phone=" 081234567890 ",
                  address=" Jl. A ")
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Budi")
        self.assertEqual(self.buyer.phone, "081234567890")
        self.assertEqual(self.buyer.address, "Jl. A")

    def test_update_profile_allows_empty_phone_and_address(self):
        self.buyer.phone = "081234567890"
        self.buyer.address = "Lama"
        self.buyer.save()
        r = self.post("profile", name="Budi", phone="", address="")
        self.assertIn("Perubahan berhasil disimpan.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.phone, "")
        self.assertEqual(self.buyer.address, "")

    def test_update_profile_seller_changes_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="Toko Baru", phone="081234567890", address="Jl. B")
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "Toko Baru")

    def test_changing_store_name_does_not_change_username(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="Toko Baru")
        seller.refresh_from_db()
        self.assertEqual(seller.username, "TokoHijau")

    def test_seller_name_does_not_touch_full_name(self):
        seller = make_seller()
        seller.full_name = "Pemilik Toko"
        seller.save()
        self.client.force_login(seller)
        self.post("profile", name="Toko Baru")
        seller.refresh_from_db()
        self.assertEqual(seller.full_name, "Pemilik Toko")

    def test_update_profile_seller_without_profile_creates_one(self):
        seller = make_user(email="s@example.com", username="s",
                           role=User.ROLE_SELLER)
        self.client.force_login(seller)
        self.post("profile", name="Toko Sementara")
        self.assertEqual(
            SellerProfile.objects.get(user=seller).store_name, "Toko Sementara")

    # --- profile: validasi nama -------------------------------------------
    def test_blank_name_is_rejected_for_buyer(self):
        self.buyer.full_name = "Budi"
        self.buyer.save()
        r = self.post("profile", name="   ", phone="081234567890")
        self.assertIn("Nama wajib diisi.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Budi")
        self.assertEqual(self.buyer.phone, "")

    def test_blank_name_is_rejected_for_seller_and_keeps_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        r = self.post("profile", name="", phone="081234567890")
        self.assertIn("Nama wajib diisi.", msgs(r))
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoHijau")

    def test_missing_name_field_is_rejected(self):
        r = self.post("profile")
        self.assertIn("Nama wajib diisi.", msgs(r))

    def test_buyer_name_length_boundary(self):
        r = self.post("profile", name="a" * 151)
        self.assertIn("Nama maksimal 150 karakter.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "")
        self.post("profile", name="a" * 150)
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "a" * 150)

    def test_seller_store_name_length_boundary(self):
        seller = make_seller()
        self.client.force_login(seller)
        r = self.post("profile", name="b" * 101)
        self.assertIn("Nama maksimal 100 karakter.", msgs(r))
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoHijau")
        self.post("profile", name="b" * 100)
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "b" * 100)

    # --- profile: nama toko kembar ----------------------------------------
    def test_update_profile_seller_duplicate_store_name_shows_error(self):
        make_seller(email="a@example.com", username="a", store_name="TokoA")
        seller = make_seller(email="b@example.com", username="b", store_name="TokoB")
        self.client.force_login(seller)
        r = self.post("profile", name="TokoA")
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertTrue(any("Nama toko sudah dipakai" in m for m in msgs(r)), msgs(r))
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoB")

    def test_duplicate_store_name_check_is_case_insensitive(self):
        make_seller(email="a@example.com", username="a", store_name="TokoA")
        seller = make_seller(email="b@example.com", username="b", store_name="TokoB")
        self.client.force_login(seller)
        self.post("profile", name="tokoa")
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoB")

    def test_duplicate_store_name_does_not_save_other_fields(self):
        make_seller(email="a@example.com", username="a", store_name="TokoA")
        seller = make_seller(email="b@example.com", username="b", store_name="TokoB")
        self.client.force_login(seller)
        self.post("profile", name="TokoA", phone="081234567890", address="Jl. X")
        seller.refresh_from_db()
        self.assertEqual(seller.phone, "")
        self.assertEqual(seller.address, "")

    def test_duplicate_store_name_for_seller_without_profile_does_not_crash(self):
        make_seller(email="a@example.com", username="a", store_name="TokoA")
        seller = make_user(email="s@example.com", username="s",
                           role=User.ROLE_SELLER)
        self.client.force_login(seller)
        r = self.post("profile", name="TokoA")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(SellerProfile.objects.filter(user=seller).exists())

    def test_seller_can_resave_own_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        r = self.post("profile", name="TokoHijau", phone="081234567890")
        self.assertIn("Perubahan berhasil disimpan.", msgs(r))

    def test_seller_can_change_only_the_case_of_own_store_name(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="tokohijau")
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "tokohijau")

    def test_buyer_full_name_can_equal_a_store_name(self):
        make_seller(store_name="Budi Santoso", username="penjual")
        r = self.post("profile", name="Budi Santoso")
        self.assertIn("Perubahan berhasil disimpan.", msgs(r))

    # --- profile: telepon & alamat ----------------------------------------
    def test_invalid_phone_numbers_are_rejected(self):
        for bad in ("abc12345", "1234567", "1" * 16, "0812 3456 7890",
                    "0812-3456-7890", "++6281234567", "62+81234567"):
            with self.subTest(phone=bad):
                r = self.post("profile", name="Budi", phone=bad)
                self.assertTrue(any("Nomor telepon" in m for m in msgs(r)), msgs(r))
                self.buyer.refresh_from_db()
                self.assertEqual(self.buyer.phone, "")

    def test_valid_phone_numbers_are_accepted(self):
        for good in ("12345678", "081234567890", "+6281234567890", "1" * 15):
            with self.subTest(phone=good):
                self.post("profile", name="Budi", phone=good)
                self.buyer.refresh_from_db()
                self.assertEqual(self.buyer.phone, good)

    def test_invalid_phone_does_not_change_name(self):
        self.post("profile", name="Nama Baru", phone="abc")
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "")

    def test_address_length_boundary(self):
        r = self.post("profile", name="Budi", address="x" * 501)
        self.assertIn("Alamat maksimal 500 karakter.", msgs(r))
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.address, "")
        self.post("profile", name="Budi", address="x" * 500)
        self.buyer.refresh_from_db()
        self.assertEqual(len(self.buyer.address), 500)

    # --- profile: logo -----------------------------------------------------
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
        self.assertTrue(os.path.exists(self.buyer.logo.path))

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
        self.assertTrue(os.path.exists(self.buyer.logo.path))

    def test_validation_error_keeps_existing_logo_file(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        path = self.buyer.logo.path
        self.post("profile", name="Budi", phone="abc", logo=make_image("JPEG"))
        self.assertTrue(os.path.exists(path))

    def test_old_logo_is_kept_and_changes_rolled_back_when_save_fails(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("profile", name="TokoHijau", logo=make_image("PNG", name="lama.png"))
        seller.refresh_from_db()
        old_name, old_path = seller.logo.name, seller.logo.path
        self.client.raise_request_exception = False
        with patch.object(User, "save", side_effect=Exception("DB error")):
            r = self.post("profile", name="Nama Toko Baru",
                          logo=make_image("JPEG", name="baru.jpg"))
        self.assertEqual(r.status_code, 500)
        self.assertTrue(os.path.exists(old_path))
        seller.refresh_from_db()
        self.assertEqual(seller.logo.name, old_name)
        seller.seller_profile.refresh_from_db()
        self.assertEqual(seller.seller_profile.store_name, "TokoHijau")   # rollback atomic

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

    # --- metode pembayaran: tambah ----------------------------------------
    def test_add_payment_success(self):
        r = self.post("add_payment", method_type="ewallet",
                      provider=EWALLET, account_number="08123456789")
        self.assertTrue(any("Metode pembayaran ditambahkan" in m for m in msgs(r)),
                        msgs(r))
        pm = PaymentMethod.objects.get(user=self.buyer)
        self.assertEqual(pm.method_type, "ewallet")
        self.assertEqual(pm.provider, EWALLET)
        self.assertEqual(pm.account_number, "08123456789")

    def test_add_payment_bank_success_for_seller(self):
        seller = make_seller()
        self.client.force_login(seller)
        self.post("add_payment", method_type="bank", provider="BCA",
                  account_number="1234567890")
        self.assertEqual(PaymentMethod.objects.filter(user=seller).count(), 1)

    def test_add_payment_strips_number(self):
        self.post("add_payment", method_type="bank", provider="BCA",
                  account_number=" 1234567890 ")
        self.assertEqual(
            PaymentMethod.objects.get(user=self.buyer).account_number, "1234567890")

    def test_add_payment_invalid_type(self):
        r = self.post("add_payment", method_type="crypto",
                      provider="BCA", account_number="12345678")
        self.assertTrue(msgs(r))
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_qris_is_not_allowed(self):
        r = self.post("add_payment", method_type="qris",
                      provider="BCA", account_number="12345678")
        self.assertTrue(msgs(r))
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_provider_not_in_list(self):
        r = self.post("add_payment", method_type="bank",
                      provider="BankAbalAbal", account_number="12345678")
        self.assertTrue(msgs(r))
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_provider_must_match_type(self):
        r = self.post("add_payment", method_type="bank",
                      provider=EWALLET, account_number="12345678")
        self.assertTrue(any("Provider" in m for m in msgs(r)), msgs(r))
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_non_digit_number(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="12ab34567890")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_number_too_short(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="1234567")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_number_too_long(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="1" * 21)
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_empty_provider(self):
        self.post("add_payment", method_type="bank",
                  provider="  ", account_number="12345678")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_empty_number(self):
        self.post("add_payment", method_type="bank",
                  provider="BCA", account_number="")
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_missing_everything(self):
        r = self.post("add_payment")
        self.assertEqual(r.status_code, 302)
        self.assertFalse(PaymentMethod.objects.exists())

    def test_add_payment_error_messages_are_shown(self):
        r = self.post("add_payment", method_type="bank", provider="BCA",
                      account_number="abc")
        self.assertTrue(msgs(r))     # bug lama: NameError saat loop error form

    def test_add_payment_limit_is_enforced(self):
        for i in range(MAX_PAYMENT_METHODS):
            self.add_payment(self.buyer, i)
        r = self.post("add_payment", method_type="bank", provider="BNI",
                      account_number="99999999")
        self.assertTrue(any("maksimal" in m.lower() for m in msgs(r)), msgs(r))
        self.assertEqual(self.buyer.payment_methods.count(), MAX_PAYMENT_METHODS)

    def test_add_payment_allowed_up_to_the_limit(self):
        for i in range(MAX_PAYMENT_METHODS - 1):
            self.add_payment(self.buyer, i)
        self.post("add_payment", method_type="bank", provider="BNI",
                  account_number="99999999")
        self.assertEqual(self.buyer.payment_methods.count(), MAX_PAYMENT_METHODS)

    def test_add_payment_limit_is_per_user(self):
        other = make_user(email="o@example.com", username="o")
        for i in range(MAX_PAYMENT_METHODS):
            self.add_payment(other, i)
        self.post("add_payment", method_type="bank", provider="BNI",
                  account_number="99999999")
        self.assertEqual(self.buyer.payment_methods.count(), 1)

    # --- metode pembayaran: hapus -----------------------------------------
    def test_delete_own_payment(self):
        pm = self.add_payment(self.buyer, 1)
        r = self.post("delete_payment", payment_id=pm.id)
        self.assertIn("Metode pembayaran dihapus.", msgs(r))
        self.assertFalse(PaymentMethod.objects.filter(pk=pm.pk).exists())

    def test_cannot_delete_other_users_payment(self):
        other = make_user(email="o@example.com", username="o")
        pm = self.add_payment(other, 1)
        r = self.post("delete_payment", payment_id=pm.id)
        self.assertTrue(PaymentMethod.objects.filter(pk=pm.pk).exists())
        self.assertNotIn("Metode pembayaran dihapus.", msgs(r))

    def test_delete_unknown_payment_id_shows_error(self):
        r = self.post("delete_payment", payment_id=999999)
        self.assertIn("Metode pembayaran tidak ditemukan.", msgs(r))

    def test_delete_payment_with_non_numeric_id_does_not_crash(self):
        pm = self.add_payment(self.buyer, 1)
        for bad in ("abc", "1abc", "-1", "1.5", " ", "٣", "1; DROP TABLE"):
            with self.subTest(payment_id=bad):
                r = self.post("delete_payment", payment_id=bad)
                self.assertEqual(r.status_code, 302)
                self.assertIn("Metode pembayaran tidak valid.", msgs(r))
        self.assertTrue(PaymentMethod.objects.filter(pk=pm.pk).exists())

    def test_delete_payment_without_id_does_not_crash(self):
        r = self.post("delete_payment")
        self.assertEqual(r.status_code, 302)
        self.assertIn("Metode pembayaran tidak valid.", msgs(r))

    def test_delete_payment_with_huge_id_does_not_crash(self):
        r = self.post("delete_payment", payment_id="9" * 40)
        self.assertEqual(r.status_code, 302)
        self.assertIn("Metode pembayaran tidak valid.", msgs(r))

    def test_delete_payment_only_deletes_the_selected_one(self):
        a = self.add_payment(self.buyer, 1)
        b = self.add_payment(self.buyer, 2)
        self.post("delete_payment", payment_id=a.id)
        self.assertFalse(PaymentMethod.objects.filter(pk=a.pk).exists())
        self.assertTrue(PaymentMethod.objects.filter(pk=b.pk).exists())

    # --- hapus akun --------------------------------------------------------
    def test_delete_account_success(self):
        pm = self.add_payment(self.buyer, 1)
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

    def test_delete_account_does_not_touch_other_users(self):
        other = make_user(email="o@example.com", username="o")
        self.post("delete_account", password=STRONG_PASSWORD)
        self.assertTrue(User.objects.filter(pk=other.pk).exists())

    def test_delete_account_removes_logo_file(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        path = self.buyer.logo.path
        self.assertTrue(os.path.exists(path))
        self.post("delete_account", password=STRONG_PASSWORD)
        self.assertFalse(os.path.exists(path))

    def test_delete_account_without_logo_does_not_crash(self):
        r = self.post("delete_account", password=STRONG_PASSWORD)
        self.assertEqual(r.status_code, 302)

    def test_delete_account_wrong_password(self):
        r = self.post("delete_account", password="salah")
        self.assertIn("Password salah. Akun tidak dihapus.", msgs(r))
        self.assertTrue(User.objects.filter(pk=self.buyer.pk).exists())

    def test_delete_account_without_password(self):
        r = self.post("delete_account")
        self.assertIn("Password salah. Akun tidak dihapus.", msgs(r))
        self.assertTrue(User.objects.filter(pk=self.buyer.pk).exists())

    def test_wrong_password_keeps_logo_file(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        self.post("delete_account", password="salah")
        self.assertTrue(os.path.exists(self.buyer.logo.path))

    def test_protected_error_keeps_account_logo_and_session(self):
        self.post("profile", name="Budi", logo=make_image("PNG"))
        self.buyer.refresh_from_db()
        path = self.buyer.logo.path
        with patch.object(User, "delete",
                          side_effect=ProtectedError("terlindungi", set())):
            r = self.post("delete_account", password=STRONG_PASSWORD)
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertTrue(any("tidak bisa dihapus" in m for m in msgs(r)), msgs(r))
        self.assertTrue(User.objects.filter(pk=self.buyer.pk).exists())
        self.assertTrue(os.path.exists(path))
        self.assertIn("_auth_user_id", self.client.session)

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

    def test_missing_action_just_redirects(self):
        r = self.client.post(self.url, {})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)