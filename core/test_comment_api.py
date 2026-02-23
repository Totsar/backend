from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Comment, CommentReport, Item


class CommentAPITests(APITestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(
            username="owner-comment@example.com",
            email="owner-comment@example.com",
            password="StrongPassword123",
            first_name="Owner",
            last_name="Comment",
        )
        self.author = self.user_model.objects.create_user(
            username="author-comment@example.com",
            email="author-comment@example.com",
            password="StrongPassword123",
            first_name="Author",
            last_name="Comment",
        )
        self.other_user = self.user_model.objects.create_user(
            username="other-comment@example.com",
            email="other-comment@example.com",
            password="StrongPassword123",
            first_name="Other",
            last_name="Comment",
        )
        self.item = Item.objects.create(
            owner=self.owner,
            title="Lost wallet",
            description="Black wallet",
            location="Library",
            item_type=Item.ItemType.LOST,
            latitude=35.7,
            longitude=51.35,
        )
        self.comment = Comment.objects.create(item=self.item, user=self.author, text="Initial comment")

    def _comment_create_url(self):
        return reverse("item-comment-create", kwargs={"item_id": self.item.id})

    def _comment_detail_url(self):
        return reverse(
            "item-comment-detail",
            kwargs={"item_id": self.item.id, "comment_id": self.comment.id},
        )

    def _comment_report_url(self, item_id=None):
        return reverse(
            "item-comment-report",
            kwargs={
                "item_id": item_id or self.item.id,
                "comment_id": self.comment.id,
            },
        )

    def test_create_comment_requires_authentication(self):
        response = self.client.post(self._comment_create_url(), {"text": "New comment"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_comment_success_for_authenticated_user(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(self._comment_create_url(), {"text": "Hello there"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Comment.objects.filter(item=self.item, user=self.other_user).count(), 1)

    def test_create_comment_non_existent_item_returns_404(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(
            reverse("item-comment-create", kwargs={"item_id": 999999}),
            {"text": "Hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_comment_author_can_update_comment(self):
        self.client.force_authenticate(user=self.author)
        response = self.client.put(self._comment_detail_url(), {"text": "Updated by author"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.comment.refresh_from_db()
        self.assertEqual(self.comment.text, "Updated by author")

    def test_non_author_cannot_update_comment(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.put(self._comment_detail_url(), {"text": "Malicious update"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_comment_author_can_delete_comment(self):
        self.client.force_authenticate(user=self.author)
        response = self.client.delete(self._comment_detail_url())

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Comment.objects.filter(id=self.comment.id).exists())

    def test_non_author_cannot_delete_comment(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(self._comment_detail_url())

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Comment.objects.filter(id=self.comment.id).exists())

    def test_comment_report_requires_authentication(self):
        response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_can_report_comment_once(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(CommentReport.objects.count(), 1)
        report = CommentReport.objects.get()
        self.assertEqual(report.user_id, self.other_user.id)
        self.assertEqual(report.comment_id, self.comment.id)
        self.assertEqual(report.reason, "spam")

    def test_duplicate_report_is_rejected(self):
        self.client.force_authenticate(user=self.other_user)
        first = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")
        second = self.client.post(self._comment_report_url(), {"reason": "offensive"}, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CommentReport.objects.count(), 1)

    def test_comment_author_cannot_report_own_comment(self):
        self.client.force_authenticate(user=self.author)
        response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CommentReport.objects.count(), 0)

    def test_removed_comment_cannot_be_reported(self):
        self.comment.is_removed = True
        self.comment.save(update_fields=["is_removed"])

        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CommentReport.objects.count(), 0)

    def test_comment_report_with_mismatched_item_returns_404(self):
        second_item = Item.objects.create(
            owner=self.owner,
            title="Found keys",
            description="Keychain",
            location="Hall",
            item_type=Item.ItemType.FOUND,
            latitude=35.71,
            longitude=51.36,
        )
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(
            self._comment_report_url(item_id=second_item.id),
            {"reason": "spam"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_comment_report_threshold_exactly_five_does_not_remove_comment(self):
        reporters = [
            self.user_model.objects.create_user(
                username=f"r{i}@example.com",
                email=f"r{i}@example.com",
                password="StrongPassword123",
                first_name=f"R{i}",
                last_name="User",
            )
            for i in range(1, 6)
        ]
        for reporter in reporters:
            self.client.force_authenticate(user=reporter)
            response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.comment.refresh_from_db()
        self.assertFalse(self.comment.is_removed)
        self.assertEqual(CommentReport.objects.filter(comment=self.comment).count(), 5)

    def test_comment_report_sixth_marks_comment_removed(self):
        reporters = [
            self.user_model.objects.create_user(
                username=f"rr{i}@example.com",
                email=f"rr{i}@example.com",
                password="StrongPassword123",
                first_name=f"RR{i}",
                last_name="User",
            )
            for i in range(1, 7)
        ]
        for reporter in reporters:
            self.client.force_authenticate(user=reporter)
            response = self.client.post(self._comment_report_url(), {"reason": "spam"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.comment.refresh_from_db()
        self.assertTrue(self.comment.is_removed)
        self.assertEqual(CommentReport.objects.filter(comment=self.comment).count(), 6)

    def test_item_detail_excludes_removed_comments(self):
        visible_comment = Comment.objects.create(item=self.item, user=self.other_user, text="Keep me")
        removed_comment = Comment.objects.create(item=self.item, user=self.owner, text="Remove me", is_removed=True)

        response = self.client.get(reverse("item-detail", kwargs={"item_id": self.item.id}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [row["id"] for row in response.data["comments"]]
        self.assertIn(visible_comment.id, returned_ids)
        self.assertNotIn(removed_comment.id, returned_ids)

    def test_comment_detail_get_returns_404_for_removed_comment(self):
        self.comment.is_removed = True
        self.comment.save(update_fields=["is_removed"])

        response = self.client.get(self._comment_detail_url())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_comment_detail_update_returns_404_for_removed_comment(self):
        self.comment.is_removed = True
        self.comment.save(update_fields=["is_removed"])
        self.client.force_authenticate(user=self.author)

        response = self.client.put(self._comment_detail_url(), {"text": "Updated"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_comment_detail_delete_returns_404_for_removed_comment(self):
        self.comment.is_removed = True
        self.comment.save(update_fields=["is_removed"])
        self.client.force_authenticate(user=self.author)

        response = self.client.delete(self._comment_detail_url())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
