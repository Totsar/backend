from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone


class User(AbstractUser):
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True)

    def save(self, *args, **kwargs):
        # Keep username populated while using email as the external identifier.
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)


class EmailOTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", "Register"

    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices, db_index=True)
    otp_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField(db_index=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def set_otp(self, otp):
        self.otp_hash = make_password(otp)

    def check_otp(self, otp):
        return check_password(otp, self.otp_hash)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Item(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="items/", blank=True, null=True)
    location = models.CharField(max_length=255)
    embedding = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    tags = models.ManyToManyField(Tag, related_name="items", blank=True)

    def __str__(self):
        return self.title


class Comment(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment {self.id} on item {self.item_id}"


class ItemReport(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="item_reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "user"], name="unique_user_item_report"),
        ]
