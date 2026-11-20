import json

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import OTPToken, SellerProfile
from .views import MAX_LOGIN_ATTEMPTS

User = get_user_model()
PASSWORD = "KataSandiKuat123"


class MobileLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse('users:login_mobile')
        self.user = User.objects.create_user(
            username='budi', email='budi@example.com', password=PASSWORD,
            full_name='Budi', role=User.ROLE_BUYER,
        )

    def test_login_success_returns_json_200_without_csrf(self):
        res = self.client.post(self.url, {'email': 'BUDI@example.com', 'password': PASSWORD})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['status'])
        self.assertEqual(data['username'], 'budi')
        self.assertEqual(data['role'], 'buyer')
        self.assertIn('sessionid', res.cookies)

    def test_login_without_remember_me_uses_browser_session(self):
        self.client.post(self.url, {'email': 'budi@example.com', 'password': PASSWORD})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_login_with_remember_me_keeps_session(self):
        self.client.post(self.url, {'email': 'budi@example.com', 'password': PASSWORD, 'remember_me': 'true'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_wrong_password_returns_401(self):
        res = self.client.post(self.url, {'email': 'budi@example.com', 'password': 'salah'})
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.json()['status'])

    def test_empty_fields_returns_400(self):
        res = self.client.post(self.url, {'email': '', 'password': ''})
        self.assertEqual(res.status_code, 400)

    def test_lockout_after_max_attempts(self):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            self.client.post(self.url, {'email': 'budi@example.com', 'password': 'salah'})
        res = self.client.post(self.url, {'email': 'budi@example.com', 'password': PASSWORD})
        self.assertEqual(res.status_code, 429)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


@override_settings(AUTH_PASSWORD_VALIDATORS=[
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
])
class MobileRegisterTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.url = reverse('users:register_mobile')
        self.otp = OTPToken.objects.create(email='baru@example.com', otp_code='123456')

    def _data(self, **kw):
        data = {
            'role': 'buyer', 'full_name': 'Baru', 'username': 'baru',
            'email': 'baru@example.com', 'otp_code': '123456',
            'password': PASSWORD, 'confirm_password': PASSWORD,
        }
        data.update(kw)
        return data

    def test_register_buyer_success(self):
        res = self.client.post(self.url, self._data())
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()['status'])
        self.assertTrue(User.objects.filter(email='baru@example.com', role='buyer').exists())
        self.otp.refresh_from_db()
        self.assertTrue(self.otp.is_used)

    def test_register_seller_creates_store(self):
        res = self.client.post(self.url, self._data(role='seller', store_name='Toko Hijau', username=''))
        self.assertEqual(res.status_code, 201)
        user = User.objects.get(email='baru@example.com')
        self.assertEqual(user.username, 'Toko Hijau')
        self.assertTrue(SellerProfile.objects.filter(user=user, store_name='Toko Hijau').exists())

    def test_wrong_otp_rejected(self):
        res = self.client.post(self.url, self._data(otp_code='000000'))
        self.assertEqual(res.status_code, 400)
        self.assertFalse(User.objects.filter(email='baru@example.com').exists())

    def test_password_mismatch_rejected(self):
        res = self.client.post(self.url, self._data(confirm_password='beda12345'))
        self.assertEqual(res.status_code, 400)
        self.assertIn('Konfirmasi', res.json()['message'])

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username='lama', email='baru@example.com', password=PASSWORD)
        res = self.client.post(self.url, self._data())
        self.assertEqual(res.status_code, 400)

    def test_seller_without_store_name_rejected(self):
        res = self.client.post(self.url, self._data(role='seller', store_name=''))
        self.assertEqual(res.status_code, 400)


class MobileOtpAndLogoutTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_send_otp_without_csrf(self):
        res = self.client.post(
            reverse('users:send_otp_mobile'),
            data=json.dumps({'email': 'otp@example.com'}),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_logout(self):
        user = User.objects.create_user(username='x', email='x@example.com', password=PASSWORD)
        self.client.force_login(user)
        res = self.client.post(reverse('users:logout_mobile'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['username'], 'x')
        self.assertNotIn('_auth_user_id', self.client.session)
