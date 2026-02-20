from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_emailotp"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="embedding",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
