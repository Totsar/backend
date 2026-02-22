import re
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import EmailOTP, Item


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


class LostItemAssistantAPITests(APITestCase):
    def setUp(self):
        self.assistant_url = reverse("lost-item-assistant")
        self.stream_url = reverse("lost-item-assistant-stream")

    @patch("core.views.find_lost_items_with_ai")
    def test_assistant_endpoint_returns_message_and_ids(self, mock_find):
        mock_find.return_value = {
            "message": "These are likely matches.",
            "picked_item_ids": [4, 7],
            "candidate_item_ids": [4, 7, 9],
        }

        response = self.client.post(self.assistant_url, {"query": "black backpack"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "These are likely matches.")
        self.assertEqual(response.data["pickedItemIds"], [4, 7])
        self.assertEqual(response.data["candidateItemIds"], [4, 7, 9])
        mock_find.assert_called_once_with(query="black backpack")

    @patch("core.views.find_lost_items_with_ai")
    def test_assistant_stream_endpoint_returns_events_including_selected_ids(self, mock_find):
        mock_find.return_value = {
            "message": "Likely item match from gate A area.",
            "picked_item_ids": [10, 12],
            "candidate_item_ids": [10, 12, 14],
        }

        response = self.client.post(self.stream_url, {"query": "airport wallet"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in response.streaming_content
        ).decode("utf-8")

        self.assertIn("event: assistant_message", body)
        self.assertIn('event: selected_item_ids\ndata: {"itemIds": [10, 12]}', body)
        self.assertIn('event: candidate_item_ids\ndata: {"itemIds": [10, 12, 14]}', body)
        self.assertIn("event: done", body)

    @patch("core.views.find_lost_items_with_ai", side_effect=RuntimeError("OPENAI_API_KEY is not configured."))
    def test_assistant_endpoint_returns_503_on_runtime_error(self, _mock_find):
        response = self.client.post(self.assistant_url, {"query": "watch"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "OPENAI_API_KEY is not configured.")

    def test_assistant_endpoint_requires_query(self):
        response = self.client.post(self.assistant_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("query", response.data)


class AIAssistantConfigTests(APITestCase):
    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://api.openai-proxy.local/v1")
    @patch("openai.OpenAI")
    def test_openai_client_uses_configured_base_url(self, mock_openai):
        from .ai_assistant import _get_openai_client

        _get_openai_client()

        mock_openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.openai-proxy.local/v1",
        )


class ItemCoordinateAPITests(APITestCase):
    def setUp(self):
        self.item_url = reverse("item-list-create")
        self.user = User.objects.create_user(
            username="mapowner@example.com",
            email="mapowner@example.com",
            password="StrongPassword123",
            first_name="Map",
            last_name="Owner",
        )
        self.client.force_authenticate(user=self.user)

    def test_create_item_with_coordinates(self):
        response = self.client.post(
            self.item_url,
            {
                "title": "Black wallet",
                "description": "Lost near library entrance.",
                "location": "Library entrance",
                "itemType": "lost",
                "latitude": 35.7025,
                "longitude": 51.3494,
                "tags": ["wallet", "black"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["itemType"], "lost")
        self.assertEqual(response.data["latitude"], 35.7025)
        self.assertEqual(response.data["longitude"], 51.3494)
        self.assertEqual(Item.objects.count(), 1)
        item = Item.objects.get()
        self.assertEqual(item.item_type, Item.ItemType.LOST)
        self.assertEqual(item.latitude, 35.7025)
        self.assertEqual(item.longitude, 51.3494)

    def test_create_item_requires_both_coordinates(self):
        response = self.client.post(
            self.item_url,
            {
                "title": "Phone",
                "description": "Blue phone",
                "location": "Main gate",
                "itemType": "lost",
                "latitude": 35.70,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_create_item_rejects_invalid_item_type(self):
        response = self.client.post(
            self.item_url,
            {
                "title": "Keys",
                "description": "Found near cafeteria.",
                "location": "Cafeteria",
                "itemType": "invalid",
                "latitude": 35.701,
                "longitude": 51.349,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("itemType", response.data)

    def test_list_items_filters_by_item_type(self):
        Item.objects.create(
            owner=self.user,
            title="Lost notebook",
            description="Black notebook",
            location="Library",
            item_type=Item.ItemType.LOST,
            latitude=35.702,
            longitude=51.35,
        )
        Item.objects.create(
            owner=self.user,
            title="Found headphones",
            description="Silver pair",
            location="Lab",
            item_type=Item.ItemType.FOUND,
            latitude=35.703,
            longitude=51.351,
        )

        response = self.client.get(f"{self.item_url}?itemType=found")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["itemType"], "found")
