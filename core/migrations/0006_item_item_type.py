from django.db import migrations, models


def backfill_item_type_lost(apps, schema_editor):
    Item = apps.get_model("core", "Item")
    Item.objects.filter(item_type__isnull=True).update(item_type="lost")
    Item.objects.filter(item_type="").update(item_type="lost")
    Item.objects.filter(item_type__in=["unknown", "unkown", "unassigned"]).update(item_type="lost")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_item_latitude_item_longitude"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="item_type",
            field=models.CharField(
                choices=[("lost", "Lost"), ("found", "Found")],
                db_index=True,
                default="lost",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_item_type_lost, migrations.RunPython.noop),
    ]
