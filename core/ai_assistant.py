import json
import math
from typing import Any

from django.conf import settings

from .models import Item


def _has_openai_config() -> bool:
    return bool(getattr(settings, "OPENAI_API_KEY", "").strip())


def _build_item_text(item: Item) -> str:
    tags = ", ".join(item.tags.values_list("name", flat=True))
    return (
        f"title: {item.title}\n"
        f"description: {item.description}\n"
        f"location: {item.location}\n"
        f"tags: {tags}"
    )


def _get_openai_client():
    from openai import OpenAI

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )


def _embed_texts(texts: list[str]) -> list[list[float]]:
    client = _get_openai_client()
    response = client.embeddings.create(
        model=settings.OPENAI_EMBEDDING_MODEL,
        input=texts,
    )
    return [row.embedding for row in response.data]


def sync_item_embedding(item: Item) -> None:
    if not _has_openai_config():
        return
    embeddings = _embed_texts([_build_item_text(item)])
    item.embedding = embeddings[0]
    item.save(update_fields=["embedding"])


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return -1.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return -1.0
    return dot_product / (norm_a * norm_b)


def _ensure_item_embeddings(items: list[Item]) -> None:
    if not _has_openai_config():
        return

    missing_items = [item for item in items if not item.embedding]
    if not missing_items:
        return

    max_items = settings.ASSISTANT_MAX_ITEMS_TO_EMBED_PER_REQUEST
    items_to_embed = missing_items[:max_items]
    texts = [_build_item_text(item) for item in items_to_embed]
    embeddings = _embed_texts(texts)

    for item, embedding in zip(items_to_embed, embeddings):
        item.embedding = embedding
    Item.objects.bulk_update(items_to_embed, ["embedding"])


def _pick_items_with_llm(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "friendly_response": "I couldn't find matching items yet. Try adding more details like color, brand, and where you lost it.",
            "picked_item_ids": [],
        }

    client = _get_openai_client()
    candidate_ids = {item["id"] for item in candidates}

    completion = client.chat.completions.create(
        model=settings.OPENAI_CHAT_MODEL,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You help users find lost items from a candidate list. "
                    "Choose the most relevant candidate IDs and explain in a friendly tone. "
                    "Return valid JSON with keys: friendly_response (string), picked_item_ids (array of integers)."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_query": query,
                        "candidates": candidates,
                    }
                ),
            },
        ],
    )

    raw_content = completion.choices[0].message.content or "{}"
    parsed = json.loads(raw_content)

    picked_ids = []
    for item_id in parsed.get("picked_item_ids", []):
        try:
            normalized_id = int(item_id)
        except (TypeError, ValueError):
            continue
        if normalized_id in candidate_ids and normalized_id not in picked_ids:
            picked_ids.append(normalized_id)

    return {
        "friendly_response": parsed.get("friendly_response", "").strip(),
        "picked_item_ids": picked_ids[:5],
    }


def find_lost_items_with_ai(query: str) -> dict[str, Any]:
    if not _has_openai_config():
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    all_items = list(Item.objects.prefetch_related("tags").all())
    if not all_items:
        return {
            "message": "There are no items in the system yet.",
            "picked_item_ids": [],
            "candidate_item_ids": [],
        }

    _ensure_item_embeddings(all_items)
    query_embedding = _embed_texts([query])[0]

    scored_candidates = []
    for item in all_items:
        if not item.embedding:
            continue
        score = _cosine_similarity(query_embedding, item.embedding)
        scored_candidates.append((score, item))

    scored_candidates.sort(key=lambda entry: entry[0], reverse=True)
    top_candidates = scored_candidates[:10]
    candidate_payload = []
    for score, item in top_candidates:
        candidate_payload.append(
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "location": item.location,
                "tags": list(item.tags.values_list("name", flat=True)),
                "cosine_score": round(score, 4),
            }
        )

    llm_pick = _pick_items_with_llm(query=query, candidates=candidate_payload)
    message = llm_pick["friendly_response"] or (
        "I found some possible matches. Check the suggested items below."
    )
    candidate_ids = [item["id"] for item in candidate_payload]

    return {
        "message": message,
        "picked_item_ids": llm_pick["picked_item_ids"],
        "candidate_item_ids": candidate_ids,
    }
