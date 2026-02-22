import core.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_item_item_type"),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=core.models.item_image_upload_path,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=["jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "heif"]
                    )
                ],
            ),
        ),
    ]
