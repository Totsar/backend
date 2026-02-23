import os
import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from PIL import Image as PillowImage

from core.models import Item


class SignalTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="signal@example.com",
            email="signal@example.com",
            password="StrongPassword123",
            first_name="Signal",
            last_name="User",
        )
        self.media_dir = tempfile.mkdtemp()
        self.override_media = override_settings(MEDIA_ROOT=self.media_dir)
        self.override_media.enable()

    def tearDown(self):
        self.override_media.disable()
        shutil.rmtree(self.media_dir, ignore_errors=True)

    def _image_file(self, filename="image.png"):
        buffer = BytesIO()
        image = PillowImage.new("RGB", (64, 64), color=(12, 34, 56))
        image.save(buffer, format="PNG")
        return SimpleUploadedFile(filename, buffer.getvalue(), content_type="image/png")

    def test_pre_save_replacing_item_image_deletes_previous_file(self):
        item = Item.objects.create(
            owner=self.user,
            title="Bag",
            description="Blue",
            location="Library",
            item_type=Item.ItemType.LOST,
            latitude=35.7,
            longitude=51.35,
            image=self._image_file("first.png"),
        )
        old_path = item.image.path
        self.assertTrue(os.path.exists(old_path))

        item.image = self._image_file("second.png")
        item.save()
        item.refresh_from_db()

        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(bool(item.image))
        self.assertTrue(os.path.exists(item.image.path))

    def test_post_delete_item_deletes_image_file(self):
        item = Item.objects.create(
            owner=self.user,
            title="Phone",
            description="White",
            location="Cafe",
            item_type=Item.ItemType.FOUND,
            latitude=35.71,
            longitude=51.36,
            image=self._image_file("delete.png"),
        )
        image_path = item.image.path
        self.assertTrue(os.path.exists(image_path))

        item.delete()

        self.assertFalse(os.path.exists(image_path))
