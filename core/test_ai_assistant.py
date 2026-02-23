from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase

from core.ai_assistant import (
    _cosine_similarity,
    _ensure_item_embeddings,
    _get_openai_client,
    _pick_items_with_llm,
    find_lost_items_with_ai,
)
from core.models import Item


class AIAssistantUnitTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="ai@example.com",
            email="ai@example.com",
            password="StrongPassword123",
            first_name="AI",
            last_name="User",
        )

    def test_cosine_similarity_returns_minus_one_for_empty_vectors(self):
        self.assertEqual(_cosine_similarity([], [1.0, 2.0]), -1.0)
        self.assertEqual(_cosine_similarity([1.0], []), -1.0)

    def test_cosine_similarity_returns_minus_one_for_mismatched_lengths(self):
        self.assertEqual(_cosine_similarity([1.0, 2.0], [1.0]), -1.0)

    def test_cosine_similarity_returns_minus_one_for_zero_norm_vector(self):
        self.assertEqual(_cosine_similarity([0.0, 0.0], [1.0, 2.0]), -1.0)
        self.assertEqual(_cosine_similarity([1.0, 2.0], [0.0, 0.0]), -1.0)

    def test_pick_items_with_llm_filters_invalid_duplicate_and_out_of_set_ids(self):
        response_content = '{"friendly_response":"Here you go","picked_item_ids":[2,"2",999,"x",1]}'
        mock_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_content))]
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        with patch("core.ai_assistant._get_openai_client", return_value=mock_client):
            result = _pick_items_with_llm(
                query="wallet",
                candidates=[
                    {"id": 1, "title": "Wallet"},
                    {"id": 2, "title": "Card holder"},
                ],
            )

        self.assertEqual(result["friendly_response"], "Here you go")
        self.assertEqual(result["picked_item_ids"], [2, 1])

    def test_pick_items_with_llm_caps_selected_items_to_five(self):
        ids = list(range(1, 11))
        response_content = '{"friendly_response":"Top picks","picked_item_ids":[1,2,3,4,5,6,7,8,9,10]}'
        mock_completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_content))]
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        with patch("core.ai_assistant._get_openai_client", return_value=mock_client):
            result = _pick_items_with_llm(
                query="bag",
                candidates=[{"id": item_id, "title": f"Item {item_id}"} for item_id in ids],
            )

        self.assertEqual(result["picked_item_ids"], [1, 2, 3, 4, 5])

    def test_pick_items_with_llm_returns_default_when_no_candidates(self):
        result = _pick_items_with_llm(query="wallet", candidates=[])
        self.assertEqual(result["picked_item_ids"], [])
        self.assertIn("couldn't find matching items", result["friendly_response"].lower())

    @override_settings(OPENAI_API_KEY="test-key")
    def test_find_lost_items_with_ai_returns_empty_payload_when_no_items(self):
        result = find_lost_items_with_ai(query="wallet")
        self.assertEqual(result["picked_item_ids"], [])
        self.assertEqual(result["candidate_item_ids"], [])
        self.assertEqual(result["message"], "There are no items in the system yet.")

    @override_settings(OPENAI_API_KEY="test-key", ASSISTANT_MAX_ITEMS_TO_EMBED_PER_REQUEST=2)
    def test_ensure_item_embeddings_respects_max_items_per_request(self):
        items = [
            Item.objects.create(
                owner=self.user,
                title=f"Item {i}",
                description="desc",
                location="loc",
                item_type=Item.ItemType.LOST,
                latitude=35.7 + i / 100,
                longitude=51.35 + i / 100,
            )
            for i in range(3)
        ]
        mock_embeddings = [[0.1, 0.2], [0.3, 0.4]]
        with patch("core.ai_assistant._embed_texts", return_value=mock_embeddings) as mocked_embed:
            _ensure_item_embeddings(items)

        mocked_embed.assert_called_once()
        embedded_texts = mocked_embed.call_args[0][0]
        self.assertEqual(len(embedded_texts), 2)
        for item in items:
            item.refresh_from_db()
        self.assertIsNotNone(items[0].embedding)
        self.assertIsNotNone(items[1].embedding)
        self.assertIsNone(items[2].embedding)

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://api.example.local/v1")
    def test_get_openai_client_uses_httpx_fallback_on_proxy_value_error(self):
        with patch("openai.OpenAI") as mocked_openai:
            mocked_openai.side_effect = [
                ValueError("Unsupported proxy URL scheme"),
                object(),
            ]
            client = _get_openai_client()

        self.assertIsNotNone(client)
        self.assertEqual(mocked_openai.call_count, 2)
        second_call_kwargs = mocked_openai.call_args_list[1].kwargs
        self.assertIn("http_client", second_call_kwargs)
        self.assertFalse(second_call_kwargs["http_client"]._trust_env)

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://api.example.local/v1")
    def test_get_openai_client_re_raises_non_proxy_value_error(self):
        with patch("openai.OpenAI", side_effect=ValueError("invalid setting")):
            with self.assertRaises(ValueError):
                _get_openai_client()

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://api.openai-proxy.local/v1")
    def test_openai_client_uses_configured_base_url(self):
        with patch("openai.OpenAI") as mock_openai:
            _get_openai_client()

        mock_openai.assert_called_once_with(
            api_key="test-key",
            base_url="https://api.openai-proxy.local/v1",
        )

    @override_settings(OPENAI_API_KEY="test-key")
    def test_find_lost_items_with_ai_uses_default_message_when_llm_response_is_blank(self):
        item = Item.objects.create(
            owner=self.user,
            title="Wallet",
            description="Black wallet",
            location="Library",
            item_type=Item.ItemType.LOST,
            latitude=35.7,
            longitude=51.35,
            embedding=[1.0, 0.0],
        )
        with patch("core.ai_assistant._embed_texts", return_value=[[1.0, 0.0]]), patch(
            "core.ai_assistant._pick_items_with_llm",
            return_value={"friendly_response": "", "picked_item_ids": [item.id]},
        ):
            result = find_lost_items_with_ai(query="wallet")

        self.assertEqual(result["message"], "I found some possible matches. Check the suggested items below.")
        self.assertEqual(result["picked_item_ids"], [item.id])
        self.assertEqual(result["candidate_item_ids"], [item.id])

    @override_settings(OPENAI_API_KEY="test-key")
    def test_find_lost_items_with_ai_limits_candidate_items_to_top_ten(self):
        for i in range(12):
            Item.objects.create(
                owner=self.user,
                title=f"Item {i}",
                description="desc",
                location="loc",
                item_type=Item.ItemType.LOST,
                latitude=35.7 + i / 100,
                longitude=51.35 + i / 100,
                embedding=[1.0, 0.0],
            )

        with patch("core.ai_assistant._embed_texts", return_value=[[1.0, 0.0]]), patch(
            "core.ai_assistant._pick_items_with_llm",
            return_value={"friendly_response": "ok", "picked_item_ids": []},
        ):
            result = find_lost_items_with_ai(query="wallet")

        self.assertEqual(len(result["candidate_item_ids"]), 10)
