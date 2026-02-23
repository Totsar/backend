import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from core.models import EmailOTP


class AuthAPITests(APITestCase):
    def setUp(self):
        self.login_url = reverse("login")
        self.refresh_url = reverse("refresh")
        self.logout_url = reverse("logout")
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="auth-user@example.com",
            email="auth-user@example.com",
            password="StrongPassword123",
            first_name="Auth",
            last_name="User",
        )

    def test_login_success_returns_tokens_and_user(self):
        response = self.client.post(
            self.login_url,
            {"email": "auth-user@example.com", "password": "StrongPassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["user"]["id"], self.user.id)
        self.assertEqual(response.data["user"]["email"], "auth-user@example.com")

    def test_login_invalid_password_returns_400(self):
        response = self.client.post(
            self.login_url,
            {"email": "auth-user@example.com", "password": "WrongPassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid email or password.", str(response.data))

    def test_login_unknown_email_returns_400(self):
        response = self.client.post(
            self.login_url,
            {"email": "unknown@example.com", "password": "StrongPassword123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid email or password.", str(response.data))

    def test_refresh_success_returns_new_access_token(self):
        refresh_token = str(RefreshToken.for_user(self.user))

        response = self.client.post(
            self.refresh_url,
            {"refreshToken": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertTrue(response.data["accessToken"])

    def test_refresh_invalid_token_returns_400(self):
        response = self.client.post(
            self.refresh_url,
            {"refreshToken": "invalid.refresh.token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid refresh token.")

    def test_refresh_missing_token_returns_400(self):
        response = self.client.post(self.refresh_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("refreshToken", response.data)

    def test_logout_success_blacklists_refresh_token(self):
        refresh = RefreshToken.for_user(self.user)
        refresh_token = str(refresh)
        token_jti = str(refresh["jti"])

        response = self.client.post(
            self.logout_url,
            {"refreshToken": refresh_token},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        outstanding = OutstandingToken.objects.get(jti=token_jti)
        self.assertTrue(BlacklistedToken.objects.filter(token=outstanding).exists())

    def test_logout_invalid_token_returns_400(self):
        response = self.client.post(
            self.logout_url,
            {"refreshToken": "invalid.refresh.token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Invalid refresh token.")

    def test_logout_missing_token_returns_400(self):
        response = self.client.post(self.logout_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("refreshToken", response.data)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationOTPFlowTests(APITestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.request_otp_url = reverse("register-request-otp")
        self.register_url = reverse("register")

    def _request_otp(self, email):
        return self.client.post(self.request_otp_url, {"email": email}, format="json")

    def _extract_otp(self):
        body = mail.outbox[-1].body
        match = re.search(r"\b(\d{6})\b", body)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_request_otp_sends_email_and_creates_record(self):
        response = self._request_otp("NewUser@Example.com")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(EmailOTP.objects.count(), 1)
        otp_record = EmailOTP.objects.get()
        self.assertEqual(otp_record.email, "newuser@example.com")
        self.assertFalse(otp_record.is_used)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("verification code", mail.outbox[0].subject.lower())

    def test_request_otp_rejects_already_registered_email(self):
        self.user_model.objects.create_user(
            username="taken@example.com",
            email="taken@example.com",
            password="StrongPassword123",
            first_name="Taken",
            last_name="User",
        )

        response = self._request_otp("taken@example.com")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EmailOTP.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_request_otp_respects_resend_cooldown(self):
        first = self._request_otp("cooldown@example.com")
        second = self._request_otp("cooldown@example.com")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EmailOTP.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_register_with_valid_otp_returns_tokens_and_user(self):
        self._request_otp("register@example.com")
        otp = self._extract_otp()

        response = self.client.post(
            self.register_url,
            {
                "email": "Register@Example.com",
                "otp": otp,
                "password": "StrongPassword123",
                "firstName": "Reza",
                "lastName": "Test",
                "phone": "0912",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["user"]["email"], "register@example.com")
        self.assertTrue(self.user_model.objects.filter(email="register@example.com").exists())

        otp_record = EmailOTP.objects.get(email="register@example.com")
        self.assertTrue(otp_record.is_used)

    def test_register_rejects_invalid_otp_and_increments_attempts(self):
        self._request_otp("wrongotp@example.com")

        response = self.client.post(
            self.register_url,
            {
                "email": "wrongotp@example.com",
                "otp": "000000",
                "password": "StrongPassword123",
                "firstName": "Wrong",
                "lastName": "Otp",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        otp_record = EmailOTP.objects.get(email="wrongotp@example.com")
        self.assertEqual(otp_record.attempt_count, 1)
        self.assertFalse(otp_record.is_used)
        self.assertFalse(self.user_model.objects.filter(email="wrongotp@example.com").exists())

    def test_register_rejects_expired_otp(self):
        otp_record = EmailOTP(
            email="expired@example.com",
            purpose=EmailOTP.Purpose.REGISTER,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        otp_record.set_otp("123456")
        otp_record.save()

        response = self.client.post(
            self.register_url,
            {
                "email": "expired@example.com",
                "otp": "123456",
                "password": "StrongPassword123",
                "firstName": "Expired",
                "lastName": "Otp",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(self.user_model.objects.filter(email="expired@example.com").exists())

    def test_otp_cannot_be_reused_after_successful_registration(self):
        self._request_otp("reuse@example.com")
        otp = self._extract_otp()
        payload = {
            "email": "reuse@example.com",
            "otp": otp,
            "password": "StrongPassword123",
            "firstName": "Reuse",
            "lastName": "Otp",
        }

        first = self.client.post(self.register_url, payload, format="json")
        second = self.client.post(self.register_url, payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.user_model.objects.filter(email="reuse@example.com").count(), 1)

    def test_otp_exceeding_max_attempts_is_invalidated(self):
        self._request_otp("attempts@example.com")
        otp = self._extract_otp()

        for _ in range(settings.REGISTRATION_OTP_MAX_ATTEMPTS):
            response = self.client.post(
                self.register_url,
                {
                    "email": "attempts@example.com",
                    "otp": "000000",
                    "password": "StrongPassword123",
                    "firstName": "Attempt",
                    "lastName": "Limit",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        otp_record = EmailOTP.objects.get(email="attempts@example.com")
        self.assertEqual(otp_record.attempt_count, settings.REGISTRATION_OTP_MAX_ATTEMPTS)
        self.assertTrue(otp_record.is_used)

        final_try = self.client.post(
            self.register_url,
            {
                "email": "attempts@example.com",
                "otp": otp,
                "password": "StrongPassword123",
                "firstName": "Attempt",
                "lastName": "Limit",
            },
            format="json",
        )
        self.assertEqual(final_try.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(self.user_model.objects.filter(email="attempts@example.com").exists())
