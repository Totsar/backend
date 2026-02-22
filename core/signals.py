from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import Item


@receiver(pre_save, sender=Item)
def delete_replaced_item_image(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        previous = Item.objects.get(pk=instance.pk)
    except Item.DoesNotExist:
        return

    if not previous.image:
        return
    if previous.image == instance.image:
        return

    previous.image.delete(save=False)


@receiver(post_delete, sender=Item)
def delete_item_image_on_delete(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)
