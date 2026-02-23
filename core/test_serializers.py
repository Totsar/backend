from django.db.models import Count
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from core.models import Comment, Item
from core.serializers import CommentReportCreateSerializer, CommentSerializer, ItemSerializer


class SerializerTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="serializer@example.com",
            email="serializer@example.com",
            password="StrongPassword123",
            first_name="Ser",
            last_name="User",
        )

    def _item_data(self, **overrides):
        data = {
            "title": "Wallet",
            "description": "Black wallet",
            "location": "Library",
            "itemType": "lost",
            "latitude": 35.7,
            "longitude": 51.35,
            "tags": ["  Wallet  ", "wallet", " Electronics "],
        }
        data.update(overrides)
        return data

    def test_item_serializer_normalizes_tags_trim_lowercase_and_deduplicates(self):
        serializer = ItemSerializer(data=self._item_data())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["tags"], ["wallet", "electronics"])

    def test_item_serializer_rejects_invalid_tags_json_string(self):
        serializer = ItemSerializer()
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_tags(["[not-valid-json"])

    def test_item_serializer_rejects_non_list_tags_payload(self):
        serializer = ItemSerializer()
        with self.assertRaises(serializers.ValidationError):
            serializer.validate_tags(123)

    def test_comment_report_serializer_preserves_trimmed_note_for_other_reason(self):
        serializer = CommentReportCreateSerializer(data={"reason": "other", "note": "  keep this note  "})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["note"], "keep this note")

    def test_comment_report_serializer_clears_note_for_non_other_reason(self):
        serializer = CommentReportCreateSerializer(data={"reason": "spam", "note": "  should clear  "})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["note"], "")

    def test_item_serializer_omits_comments_in_non_get_representation(self):
        item = Item.objects.create(
            owner=self.user,
            title="Backpack",
            description="Blue one",
            location="Lab",
            item_type=Item.ItemType.LOST,
            latitude=35.8,
            longitude=51.4,
        )
        Comment.objects.create(item=item, user=self.user, text="comment")
        request = APIRequestFactory().post("/api/item")
        serializer = ItemSerializer(instance=item, context={"request": request})
        data = serializer.data

        self.assertNotIn("comments", data)

    def test_comment_serializer_report_count_uses_annotated_value(self):
        item = Item.objects.create(
            owner=self.user,
            title="Book",
            description="A book",
            location="Hall",
            item_type=Item.ItemType.LOST,
            latitude=35.8,
            longitude=51.4,
        )
        comment = Comment.objects.create(item=item, user=self.user, text="comment")
        annotated = (
            Comment.objects.filter(pk=comment.pk)
            .annotate(report_count=Count("reports"))
            .get()
        )

        request = APIRequestFactory().get("/api/item")
        request.user = self.user
        data = CommentSerializer(instance=annotated, context={"request": request}).data

        self.assertEqual(data["reportCount"], 0)

    def test_comment_serializer_is_reported_by_me_and_can_report_for_reporter(self):
        reporter = self.user_model.objects.create_user(
            username="reporter-serializer@example.com",
            email="reporter-serializer@example.com",
            password="StrongPassword123",
            first_name="Reporter",
            last_name="User",
        )
        item = Item.objects.create(
            owner=self.user,
            title="Watch",
            description="Silver watch",
            location="Cafe",
            item_type=Item.ItemType.FOUND,
            latitude=35.81,
            longitude=51.41,
        )
        comment = Comment.objects.create(item=item, user=self.user, text="comment")

        request_before = APIRequestFactory().get("/api/item")
        request_before.user = reporter
        before_data = CommentSerializer(instance=comment, context={"request": request_before}).data
        self.assertFalse(before_data["isReportedByMe"])
        self.assertTrue(before_data["canReport"])

        comment.reports.create(user=reporter, reason="spam")
        request_after = APIRequestFactory().get("/api/item")
        request_after.user = reporter
        after_data = CommentSerializer(instance=comment, context={"request": request_after}).data
        self.assertTrue(after_data["isReportedByMe"])
        self.assertFalse(after_data["canReport"])

    def test_comment_serializer_can_report_false_for_author_and_removed_comment(self):
        other_user = self.user_model.objects.create_user(
            username="viewer-serializer@example.com",
            email="viewer-serializer@example.com",
            password="StrongPassword123",
            first_name="Viewer",
            last_name="User",
        )
        item = Item.objects.create(
            owner=self.user,
            title="Bottle",
            description="Green bottle",
            location="Gym",
            item_type=Item.ItemType.LOST,
            latitude=35.82,
            longitude=51.42,
        )
        comment = Comment.objects.create(item=item, user=self.user, text="comment")

        author_request = APIRequestFactory().get("/api/item")
        author_request.user = self.user
        author_data = CommentSerializer(instance=comment, context={"request": author_request}).data
        self.assertFalse(author_data["canReport"])

        comment.is_removed = True
        comment.save(update_fields=["is_removed"])
        viewer_request = APIRequestFactory().get("/api/item")
        viewer_request.user = other_user
        removed_data = CommentSerializer(instance=comment, context={"request": viewer_request}).data
        self.assertFalse(removed_data["canReport"])
