from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class AssistantAPITests(APITestCase):
    def setUp(self):
        self.stream_url = reverse("lost-item-assistant-stream")
        self.assistant_url = reverse("lost-item-assistant")

    def test_assistant_stream_returns_503_on_runtime_error(self):
        with patch(
            "core.views.find_lost_items_with_ai",
            side_effect=RuntimeError("OPENAI_API_KEY is not configured."),
        ):
            response = self.client.post(self.stream_url, {"query": "wallet"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "OPENAI_API_KEY is not configured.")

    def test_assistant_stream_returns_fallback_503_on_unexpected_exception(self):
        with patch("core.views.find_lost_items_with_ai", side_effect=Exception("boom")):
            response = self.client.post(self.stream_url, {"query": "wallet"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "The assistant is currently unavailable. Please try again.")

    def test_assistant_stream_sets_sse_response_headers(self):
        mock_result = {
            "message": "Potential matches available",
            "picked_item_ids": [1],
            "candidate_item_ids": [1, 2],
        }
        with patch("core.views.find_lost_items_with_ai", return_value=mock_result):
            response = self.client.post(self.stream_url, {"query": "wallet"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertEqual(response["Cache-Control"], "no-cache")
        self.assertEqual(response["Connection"], "keep-alive")
        self.assertEqual(response["X-Accel-Buffering"], "no")

    def test_assistant_stream_splits_long_message_into_multiple_chunks(self):
        long_message = "x" * 201
        mock_result = {
            "message": long_message,
            "picked_item_ids": [10, 12],
            "candidate_item_ids": [10, 12, 14],
        }
        with patch("core.views.find_lost_items_with_ai", return_value=mock_result):
            response = self.client.post(self.stream_url, {"query": "airport wallet"}, format="json")

        body = b"".join(
            chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            for chunk in response.streaming_content
        ).decode("utf-8")

        self.assertGreaterEqual(body.count("event: assistant_message"), 3)
        self.assertIn("event: selected_item_ids", body)
        self.assertIn("event: candidate_item_ids", body)
        self.assertIn("event: done", body)

    def test_assistant_endpoint_returns_message_and_ids(self):
        mock_result = {
            "message": "These are likely matches.",
            "picked_item_ids": [4, 7],
            "candidate_item_ids": [4, 7, 9],
        }
        with patch("core.views.find_lost_items_with_ai", return_value=mock_result) as mock_find:
            response = self.client.post(self.assistant_url, {"query": "black backpack"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "These are likely matches.")
        self.assertEqual(response.data["pickedItemIds"], [4, 7])
        self.assertEqual(response.data["candidateItemIds"], [4, 7, 9])
        mock_find.assert_called_once_with(query="black backpack")

    def test_assistant_endpoint_returns_503_on_runtime_error(self):
        with patch(
            "core.views.find_lost_items_with_ai",
            side_effect=RuntimeError("OPENAI_API_KEY is not configured."),
        ):
            response = self.client.post(self.assistant_url, {"query": "watch"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "OPENAI_API_KEY is not configured.")

    def test_assistant_endpoint_requires_query(self):
        response = self.client.post(self.assistant_url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("query", response.data)

    def test_assistant_stream_endpoint_returns_events_including_selected_ids(self):
        mock_result = {
            "message": "Likely item match from gate A area.",
            "picked_item_ids": [10, 12],
            "candidate_item_ids": [10, 12, 14],
        }
        with patch("core.views.find_lost_items_with_ai", return_value=mock_result):
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

    def test_assistant_endpoint_returns_fallback_503_on_unexpected_exception(self):
        with patch("core.views.find_lost_items_with_ai", side_effect=Exception("boom")):
            response = self.client.post(self.assistant_url, {"query": "wallet"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["detail"], "The assistant is currently unavailable. Please try again.")
