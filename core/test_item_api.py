import os
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from datetime import timedelta
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image as PillowImage
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Item, ItemReport, Tag


class ItemAPITests(APITestCase):
    def setUp(self):
        self.item_url = reverse("item-list-create")
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(
            username="owner-item@example.com",
            email="owner-item@example.com",
            password="StrongPassword123",
            first_name="Owner",
            last_name="Item",
        )
        self.other_user = self.user_model.objects.create_user(
            username="other-item@example.com",
            email="other-item@example.com",
            password="StrongPassword123",
            first_name="Other",
            last_name="User",
        )
        self.item = Item.objects.create(
            owner=self.owner,
            title="Lost backpack",
            description="Blue backpack with stickers",
            location="Library",
            item_type=Item.ItemType.LOST,
            latitude=35.7,
            longitude=51.35,
        )

    def _base_payload(self, **overrides):
        payload = {
            "title": "Found Wallet",
            "description": "Black leather wallet",
            "location": "Main gate",
            "itemType": "found",
            "latitude": 35.71,
            "longitude": 51.34,
        }
        payload.update(overrides)
        return payload

    def test_create_item_requires_authentication(self):
        response = self.client.post(self.item_url, self._base_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_item_owner_can_update_item(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.put(
            reverse("item-detail", kwargs={"item_id": self.item.id}),
            self._base_payload(title="Updated title", itemType="lost"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Updated title")

    def test_non_owner_cannot_update_item(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.put(
            reverse("item-detail", kwargs={"item_id": self.item.id}),
            self._base_payload(title="Hacked title"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_item_owner_can_delete_item(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.delete(reverse("item-detail", kwargs={"item_id": self.item.id}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Item.objects.filter(id=self.item.id).exists())

    def test_non_owner_cannot_delete_item(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.delete(reverse("item-detail", kwargs={"item_id": self.item.id}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Item.objects.filter(id=self.item.id).exists())

    def test_list_items_filters_by_search_across_title_description_location(self):
        Item.objects.create(
            owner=self.owner,
            title="Umbrella",
            description="Plain",
            location="Sports hall",
            item_type=Item.ItemType.FOUND,
            latitude=35.72,
            longitude=51.36,
        )
        Item.objects.create(
            owner=self.owner,
            title="Laptop",
            description="Found in chemistry lab",
            location="Building B",
            item_type=Item.ItemType.FOUND,
            latitude=35.73,
            longitude=51.37,
        )
        Item.objects.create(
            owner=self.owner,
            title="Bottle",
            description="Reusable",
            location="Chemistry lab entrance",
            item_type=Item.ItemType.FOUND,
            latitude=35.74,
            longitude=51.38,
        )

        response = self.client.get(f"{self.item_url}?search=chemistry")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_list_items_filters_by_tag_case_insensitive(self):
        self.item.tags.add(Tag.objects.get_or_create(name="wallet")[0])
        other_item = Item.objects.create(
            owner=self.owner,
            title="Phone",
            description="White phone",
            location="Cafe",
            item_type=Item.ItemType.FOUND,
            latitude=35.75,
            longitude=51.39,
        )
        other_item.tags.add(Tag.objects.get_or_create(name="phone")[0])

        response = self.client.get(f"{self.item_url}?tag=WALLET")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.item.id)

    def test_list_items_filters_by_owner(self):
        other_item = Item.objects.create(
            owner=self.other_user,
            title="Keys",
            description="Silver keys",
            location="Dorm",
            item_type=Item.ItemType.LOST,
            latitude=35.76,
            longitude=51.40,
        )
        response = self.client.get(f"{self.item_url}?owner={self.other_user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], other_item.id)

    def test_list_items_accepts_item_type_alias_item_type(self):
        found_item = Item.objects.create(
            owner=self.owner,
            title="Found ID card",
            description="Student card",
            location="Gate",
            item_type=Item.ItemType.FOUND,
            latitude=35.77,
            longitude=51.41,
        )
        response = self.client.get(f"{self.item_url}?item_type=found")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], found_item.id)

    def test_create_item_with_coordinates(self):
        self.client.force_authenticate(user=self.owner)
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
        item = Item.objects.get(id=response.data["id"])
        self.assertEqual(item.item_type, Item.ItemType.LOST)
        self.assertEqual(item.latitude, 35.7025)
        self.assertEqual(item.longitude, 51.3494)

    def test_create_item_requires_both_coordinates(self):
        self.client.force_authenticate(user=self.owner)
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
        self.client.force_authenticate(user=self.owner)
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
            owner=self.owner,
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

    def test_list_items_are_sorted_by_created_at_descending(self):
        older = Item.objects.create(
            owner=self.owner,
            title="Old item",
            description="Old desc",
            location="Old place",
            item_type=Item.ItemType.LOST,
            latitude=35.6,
            longitude=51.2,
        )
        newer = Item.objects.create(
            owner=self.owner,
            title="New item",
            description="New desc",
            location="New place",
            item_type=Item.ItemType.LOST,
            latitude=35.9,
            longitude=51.5,
        )
        Item.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(days=1))
        Item.objects.filter(id=newer.id).update(created_at=timezone.now())
        self.item.refresh_from_db()

        response = self.client.get(self.item_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item_row["id"] for item_row in response.data]
        self.assertLess(returned_ids.index(newer.id), returned_ids.index(older.id))

    def test_update_item_rejects_single_coordinate_only(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.put(
            reverse("item-detail", kwargs={"item_id": self.item.id}),
            self._base_payload(itemType="lost", longitude=None),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("detail", response.data)

    def test_create_item_rejects_out_of_range_latitude(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.item_url,
            self._base_payload(latitude=95),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("latitude", response.data)

    def test_create_item_rejects_out_of_range_longitude(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            self.item_url,
            self._base_payload(longitude=195),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("longitude", response.data)

    def test_item_report_requires_authentication(self):
        response = self.client.post(
            reverse("item-report", kwargs={"item_id": self.item.id}),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_item_report_is_idempotent_for_same_user_and_item(self):
        self.client.force_authenticate(user=self.other_user)
        report_url = reverse("item-report", kwargs={"item_id": self.item.id})
        first = self.client.post(report_url, format="json")
        second = self.client.post(report_url, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ItemReport.objects.filter(item=self.item, user=self.other_user).count(),
            1,
        )

    def test_item_report_non_existent_item_returns_404(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(reverse("item-report", kwargs={"item_id": 999999}), format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ItemImageUploadAPITests(APITestCase):
    def setUp(self):
        self.item_url = reverse("item-list-create")
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="image-owner@example.com",
            email="image-owner@example.com",
            password="StrongPassword123",
            first_name="Image",
            last_name="Owner",
        )
        self.client.force_authenticate(user=self.user)
        self.media_dir = tempfile.mkdtemp()
        self.override_media = override_settings(MEDIA_ROOT=self.media_dir)
        self.override_media.enable()

    def tearDown(self):
        self.override_media.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _build_image_file(self, filename="item.png", image_format="PNG", size=(120, 120), color=(20, 120, 180)):
        buffer = BytesIO()
        image = PillowImage.new("RGB", size, color=color)
        image.save(buffer, format=image_format)
        return SimpleUploadedFile(
            filename,
            buffer.getvalue(),
            content_type=f"image/{image_format.lower()}",
        )

    def _multipart_payload(self, **overrides):
        payload = {
            "title": "Backpack",
            "description": "Blue backpack",
            "location": "Library",
            "itemType": "lost",
            "latitude": "35.7025",
            "longitude": "51.3494",
            "tags[0]": "bag",
            "tags[1]": "electronics",
        }
        payload.update(overrides)
        return payload

    def test_create_item_with_image_upload(self):
        response = self.client.post(
            self.item_url,
            self._multipart_payload(image=self._build_image_file()),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["image"])
        item = Item.objects.get(id=response.data["id"])
        self.assertTrue(item.image.name.startswith("items/"))
        self.assertTrue(os.path.exists(item.image.path))

    def test_create_item_rejects_non_image_upload(self):
        text_file = SimpleUploadedFile("item.txt", b"hello", content_type="text/plain")
        response = self.client.post(
            self.item_url,
            self._multipart_payload(image=text_file),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image", response.data)

    @override_settings(ITEM_IMAGE_MAX_BYTES=2000)
    def test_create_item_rejects_oversized_image(self):
        large_image = self._build_image_file(filename="large.bmp", image_format="BMP", size=(1000, 1000))
        response = self.client.post(
            self.item_url,
            self._multipart_payload(image=large_image),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("image", response.data)

    def test_update_item_remove_image_deletes_file(self):
        created = self.client.post(
            self.item_url,
            self._multipart_payload(image=self._build_image_file()),
            format="multipart",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        item_id = created.data["id"]
        item = Item.objects.get(id=item_id)
        old_image_path = item.image.path
        self.assertTrue(os.path.exists(old_image_path))

        response = self.client.put(
            reverse("item-detail", kwargs={"item_id": item_id}),
            self._multipart_payload(removeImage="true"),
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertFalse(bool(item.image))
        self.assertFalse(os.path.exists(old_image_path))

    def test_delete_item_deletes_image_file(self):
        created = self.client.post(
            self.item_url,
            self._multipart_payload(image=self._build_image_file()),
            format="multipart",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)

        item_id = created.data["id"]
        item = Item.objects.get(id=item_id)
        image_path = item.image.path
        self.assertTrue(os.path.exists(image_path))

        response = self.client.delete(reverse("item-detail", kwargs={"item_id": item_id}))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(os.path.exists(image_path))
