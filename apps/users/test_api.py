import io
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.authtoken.models import Token

from .models import OTPToken, PaymentMethod, SellerProfile


User = get_user_model()


def valid_png(name="logo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color="green").save(buffer, format="PNG")
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="image/png",
    )


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class UsersDRFAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.buyer = User.objects.create_user(
            username="buyer_drf",
            email="buyer_drf@example.com",
            password="PasswordKu123!",
            full_name="Pembeli DRF",
            role=User.ROLE_BUYER,
            phone="081234567890",
            address="Jl. Hijau Lestari No. 1",
        )
        self.seller = User.objects.create_user(
            username="Toko Hijau DRF",
            email="seller_drf@example.com",
            password="PasswordKu123!",
            full_name="Penjual DRF",
            role=User.ROLE_SELLER,
        )
        self.seller_profile = SellerProfile.objects.create(
            user=self.seller,
            store_name="Toko Hijau DRF",
        )
        self.other_seller = User.objects.create_user(
            username="Toko Bambu",
            email="seller2_drf@example.com",
            password="PasswordKu123!",
            full_name="Penjual Dua",
            role=User.ROLE_SELLER,
        )
        SellerProfile.objects.create(
            user=self.other_seller,
            store_name="Toko Bambu",
        )

    @patch("apps.users.api_views.send_mail")
    def test_send_otp_success_and_cooldown(self, mock_send_mail):
        url = reverse("users_api:send-otp")
        res = self.client.post(
            url,
            data={"email": "newuser@example.com"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            OTPToken.objects.filter(
                email="newuser@example.com",
                is_used=False,
            ).exists()
        )
        mock_send_mail.assert_called_once()

        # Cooldown < 60s returns 429
        res_cooldown = self.client.post(
            url,
            data={"email": "newuser@example.com"},
            content_type="application/json",
        )
        self.assertEqual(res_cooldown.status_code, 429)

    def test_send_otp_rejects_registered_email(self):
        url = reverse("users_api:send-otp")
        res = self.client.post(
            url,
            data={"email": self.buyer.email},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)

    @patch(
        "apps.users.api_views.send_mail",
        side_effect=RuntimeError("SMTP down"),
    )
    def test_send_otp_mail_failure_cleans_up_token(self, _mock_mail):
        url = reverse("users_api:send-otp")
        res = self.client.post(
            url,
            data={"email": "failmail@example.com"},
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 500)
        self.assertFalse(
            OTPToken.objects.filter(email="failmail@example.com").exists()
        )

    def test_register_buyer_and_seller_success(self):
        url = reverse("users_api:register")
        OTPToken.objects.create(
            email="calonbuyer@example.com",
            otp_code="123456",
        )
        res = self.client.post(
            url,
            data={
                "role": "buyer",
                "full_name": "Calon Buyer",
                "username": "calonbuyer",
                "email": "calonbuyer@example.com",
                "otp_code": "123456",
                "password": "PasswordAman123!",
                "confirm_password": "PasswordAman123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertIn("token", body)
        self.assertEqual(body["user"]["email"], "calonbuyer@example.com")
        self.assertEqual(body["user"]["role"], "buyer")

        # Register seller
        OTPToken.objects.create(
            email="calonseller@example.com",
            otp_code="654321",
        )
        res_seller = self.client.post(
            url,
            data={
                "role": "seller",
                "full_name": "Calon Seller",
                "store_name": "Toko Lestari Baru",
                "email": "calonseller@example.com",
                "otp_code": "654321",
                "password": "PasswordAman123!",
                "confirm_password": "PasswordAman123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_seller.status_code, 201)
        seller_body = res_seller.json()
        self.assertEqual(
            seller_body["user"]["store_name"],
            "Toko Lestari Baru",
        )
        self.assertTrue(
            SellerProfile.objects.filter(
                store_name="Toko Lestari Baru"
            ).exists()
        )

    def test_register_validation_and_otp_attempts(self):
        url = reverse("users_api:register")
        otp = OTPToken.objects.create(
            email="ujiotp@example.com",
            otp_code="111222",
            attempts=5,
        )
        res_locked = self.client.post(
            url,
            data={
                "role": "buyer",
                "full_name": "Uji OTP",
                "username": "ujiotp",
                "email": "ujiotp@example.com",
                "otp_code": "111222",
                "password": "PasswordAman123!",
                "confirm_password": "PasswordAman123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_locked.status_code, 429)

        # Wrong OTP code
        otp.attempts = 0
        otp.save()
        res_wrong = self.client.post(
            url,
            data={
                "role": "buyer",
                "full_name": "Uji OTP",
                "username": "ujiotp",
                "email": "ujiotp@example.com",
                "otp_code": "999999",
                "password": "PasswordAman123!",
                "confirm_password": "PasswordAman123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_wrong.status_code, 400)

    def test_login_token_auth_and_logout(self):
        login_url = reverse("users_api:login")
        res = self.client.post(
            login_url,
            data={
                "email": self.buyer.email,
                "password": "PasswordKu123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        token_key = res.json()["token"]
        self.assertTrue(Token.objects.filter(key=token_key).exists())

        # Clear session cookies and authenticate purely via Token header
        self.client.logout()
        profile_url = reverse("users_api:profile")
        res_profile = self.client.get(
            profile_url,
            HTTP_AUTHORIZATION=f"Token {token_key}",
        )
        self.assertEqual(res_profile.status_code, 200)
        self.assertEqual(res_profile.json()["email"], self.buyer.email)

        # Logout revokes token
        logout_url = reverse("users_api:logout")
        res_logout = self.client.post(
            logout_url,
            HTTP_AUTHORIZATION=f"Token {token_key}",
        )
        self.assertEqual(res_logout.status_code, 200)
        self.assertFalse(Token.objects.filter(key=token_key).exists())

    def test_login_rate_limit_lockout(self):
        login_url = reverse("users_api:login")
        for _ in range(5):
            res = self.client.post(
                login_url,
                data={
                    "email": self.buyer.email,
                    "password": "SalahPassword!",
                },
                content_type="application/json",
            )
            self.assertEqual(res.status_code, 400)

        res_locked = self.client.post(
            login_url,
            data={
                "email": self.buyer.email,
                "password": "PasswordKu123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_locked.status_code, 429)

    def test_profile_get_and_update_buyer_and_seller(self):
        profile_url = reverse("users_api:profile")
        self.client.force_login(self.buyer)

        res_get = self.client.get(profile_url)
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["full_name"], "Pembeli DRF")

        # Update buyer profile
        res_patch = self.client.patch(
            profile_url,
            data={
                "name": "Pembeli DRF Baru",
                "phone": "+6281122334455",
                "address": "Jl. Melati No. 10",
            },
            content_type="application/json",
        )
        self.assertEqual(res_patch.status_code, 200)
        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.full_name, "Pembeli DRF Baru")
        self.assertEqual(self.buyer.phone, "+6281122334455")

        # Update seller store_name and check duplicate store_name rejection
        self.client.force_login(self.seller)
        res_dup = self.client.patch(
            profile_url,
            data={"name": "Toko Bambu"},
            content_type="application/json",
        )
        self.assertEqual(res_dup.status_code, 400)

        res_seller_ok = self.client.put(
            profile_url,
            data={
                "store_name": "Toko Hijau Lestari",
                "phone": "081298765432",
                "address": "Bandung",
            },
            content_type="application/json",
        )
        self.assertEqual(res_seller_ok.status_code, 200)
        self.seller_profile.refresh_from_db()
        self.assertEqual(self.seller_profile.store_name, "Toko Hijau Lestari")

    def test_password_change_api(self):
        url = reverse("users_api:password")
        self.client.force_login(self.buyer)

        res_wrong = self.client.post(
            url,
            data={
                "old_password": "SalahPassword",
                "new_password": "PasswordBaru123!",
                "confirm_password": "PasswordBaru123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_wrong.status_code, 400)

        res_ok = self.client.post(
            url,
            data={
                "old_password": "PasswordKu123!",
                "new_password": "PasswordBaru123!",
                "confirm_password": "PasswordBaru123!",
            },
            content_type="application/json",
        )
        self.assertEqual(res_ok.status_code, 200)
        self.buyer.refresh_from_db()
        self.assertTrue(self.buyer.check_password("PasswordBaru123!"))

    def test_payment_methods_crud_and_limit(self):
        list_url = reverse("users_api:payment-methods")
        self.client.force_login(self.buyer)

        # Invalid provider for bank
        res_bad = self.client.post(
            list_url,
            data={
                "method_type": "bank",
                "provider": "Gopay",
                "account_number": "1234567890",
            },
            content_type="application/json",
        )
        self.assertEqual(res_bad.status_code, 400)

        # Create 5 valid payment methods
        created_ids = []
        for idx in range(5):
            res_create = self.client.post(
                list_url,
                data={
                    "method_type": "bank",
                    "provider": "BCA",
                    "account_number": f"123456789{idx}",
                },
                content_type="application/json",
            )
            self.assertEqual(res_create.status_code, 201)
            created_ids.append(res_create.json()["payment_method"]["id"])

        # 6th payment method rejected (max 5)
        res_limit = self.client.post(
            list_url,
            data={
                "method_type": "ewallet",
                "provider": "Gopay",
                "account_number": "081234567890",
            },
            content_type="application/json",
        )
        self.assertEqual(res_limit.status_code, 400)

        # List payment methods
        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()["payment_methods"]), 5)

        # Delete one payment method
        detail_url = reverse(
            "users_api:payment-method-detail",
            kwargs={"payment_id": created_ids[0]},
        )
        res_del = self.client.delete(detail_url)
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(
            PaymentMethod.objects.filter(user=self.buyer).count(),
            4,
        )

    def test_account_delete_api(self):
        delete_url = reverse("users_api:account-delete")

        # Superuser cannot delete account here
        admin = User.objects.create_superuser(
            username="admin_drf",
            email="admin_drf@example.com",
            password="PasswordKu123!",
        )
        self.client.force_login(admin)
        res_admin = self.client.post(
            delete_url,
            data={"password": "PasswordKu123!"},
            content_type="application/json",
        )
        self.assertEqual(res_admin.status_code, 403)

        # Regular user deletes account
        self.client.force_login(self.buyer)
        res_wrong = self.client.post(
            delete_url,
            data={"password": "Salah"},
            content_type="application/json",
        )
        self.assertEqual(res_wrong.status_code, 400)

        res_ok = self.client.delete(
            delete_url,
            data={"password": "PasswordKu123!"},
            content_type="application/json",
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertFalse(User.objects.filter(id=self.buyer.id).exists())
