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

from .models import EmailOTP


User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationOTPFlowTests(APITestCase):
    def setUp(self):
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
        User.objects.create_user(
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
        self.assertTrue(User.objects.filter(email="register@example.com").exists())

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
        self.assertFalse(User.objects.filter(email="wrongotp@example.com").exists())

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
        self.assertFalse(User.objects.filter(email="expired@example.com").exists())

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
        self.assertEqual(User.objects.filter(email="reuse@example.com").count(), 1)

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
        self.assertFalse(User.objects.filter(email="attempts@example.com").exists())
