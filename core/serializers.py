import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .ai_assistant import sync_item_embedding
from .models import Comment, EmailOTP, Item, Tag


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source="first_name")
    lastName = serializers.CharField(source="last_name")

    class Meta:
        model = User
        fields = ["id", "firstName", "lastName", "email", "phone"]


class RequestRegisterOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        normalized = value.lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def create(self, validated_data):
        email = validated_data["email"]
        now = timezone.now()
        active_otp = (
            EmailOTP.objects.filter(
                email=email,
                purpose=EmailOTP.Purpose.REGISTER,
                is_used=False,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )

        if active_otp:
            cooldown_window = active_otp.created_at + timedelta(
                seconds=settings.REGISTRATION_OTP_RESEND_COOLDOWN_SECONDS
            )
            if now < cooldown_window:
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "Please wait before requesting another OTP."
                        )
                    }
                )
            active_otp.is_used = True
            active_otp.save(update_fields=["is_used", "updated_at"])

        otp = f"{secrets.randbelow(1_000_000):06d}"
        otp_record = EmailOTP(
            email=email,
            purpose=EmailOTP.Purpose.REGISTER,
            expires_at=now + timedelta(seconds=settings.REGISTRATION_OTP_TTL_SECONDS),
        )
        otp_record.set_otp(otp)
        otp_record.save()

        ttl_minutes = max(settings.REGISTRATION_OTP_TTL_SECONDS // 60, 1)
        send_mail(
            subject="Your verification code",
            message=f"Your verification code is {otp}. It expires in {ttl_minutes} minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )
        return otp_record


class RegisterSerializer(serializers.Serializer):
    firstName = serializers.CharField(max_length=150)
    lastName = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    otp = serializers.RegexField(regex=r"^\d{6}$")
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        return value.lower()

    def validate(self, attrs):
        email = attrs["email"]
        now = timezone.now()
        otp_record = (
            EmailOTP.objects.filter(
                email=email,
                purpose=EmailOTP.Purpose.REGISTER,
                is_used=False,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if otp_record is None:
            raise serializers.ValidationError({"otp": "OTP is invalid or expired."})

        attrs["otp_record_id"] = otp_record.id
        return attrs

    def create(self, validated_data):
        otp = validated_data.pop("otp")
        otp_record_id = validated_data.pop("otp_record_id")
        email = validated_data["email"]
        otp_record = (
            EmailOTP.objects.filter(
                id=otp_record_id,
                email=email,
                purpose=EmailOTP.Purpose.REGISTER,
            ).first()
        )
        if otp_record is None or otp_record.is_used or otp_record.is_expired:
            raise serializers.ValidationError({"otp": "OTP is invalid or expired."})

        if otp_record.attempt_count >= settings.REGISTRATION_OTP_MAX_ATTEMPTS:
            otp_record.is_used = True
            otp_record.save(update_fields=["is_used", "updated_at"])
            raise serializers.ValidationError(
                {"otp": "OTP has exceeded the maximum attempts. Request a new code."}
            )

        if not otp_record.check_otp(otp):
            otp_record.attempt_count += 1
            update_fields = ["attempt_count", "updated_at"]
            if otp_record.attempt_count >= settings.REGISTRATION_OTP_MAX_ATTEMPTS:
                otp_record.is_used = True
                update_fields.append("is_used")
            otp_record.save(update_fields=update_fields)
            raise serializers.ValidationError({"otp": "Invalid OTP."})

        with transaction.atomic():
            locked_otp_record = (
                EmailOTP.objects.select_for_update()
                .filter(
                    id=otp_record_id,
                    email=email,
                    purpose=EmailOTP.Purpose.REGISTER,
                )
                .first()
            )
            if locked_otp_record is None or locked_otp_record.is_used or locked_otp_record.is_expired:
                raise serializers.ValidationError({"otp": "OTP is invalid or expired."})

            if User.objects.filter(email__iexact=email).exists():
                raise serializers.ValidationError({"email": "A user with this email already exists."})

            user = User.objects.create_user(
                username=email,
                email=email,
                first_name=validated_data["firstName"],
                last_name=validated_data["lastName"],
                phone=validated_data.get("phone", ""),
                password=validated_data["password"],
            )
            locked_otp_record.is_used = True
            locked_otp_record.save(update_fields=["is_used", "updated_at"])
            return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower()
        password = attrs["password"]
        user = User.objects.filter(email__iexact=email).first()

        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid email or password.")

        attrs["user"] = user
        return attrs


class RefreshSerializer(serializers.Serializer):
    refreshToken = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refreshToken = serializers.CharField()


class CommentSerializer(serializers.ModelSerializer):
    userId = serializers.IntegerField(source="user_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "userId", "text", "createdAt"]


class ItemSerializer(serializers.ModelSerializer):
    userId = serializers.IntegerField(source="owner_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    itemType = serializers.ChoiceField(
        source="item_type",
        choices=Item.ItemType.choices,
        required=False,
    )
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    tags = serializers.ListField(child=serializers.CharField(max_length=50), required=False, write_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "userId",
            "title",
            "description",
            "image",
            "location",
            "itemType",
            "latitude",
            "longitude",
            "createdAt",
            "tags",
            "comments",
        ]

    def validate(self, attrs):
        latitude = attrs.get("latitude")
        longitude = attrs.get("longitude")

        if self.instance is None:
            if latitude is None or longitude is None:
                raise serializers.ValidationError(
                    {"detail": "Both latitude and longitude are required."}
                )
            return attrs

        # Keep existing coordinates if they were not included in update payload.
        effective_latitude = latitude if "latitude" in attrs else self.instance.latitude
        effective_longitude = longitude if "longitude" in attrs else self.instance.longitude

        if (effective_latitude is None) != (effective_longitude is None):
            raise serializers.ValidationError(
                {"detail": "Latitude and longitude must be provided together."}
            )

        return attrs

    def _upsert_tags(self, item, tags):
        if tags is None:
            return
        normalized = sorted(set(tag.strip().lower() for tag in tags if tag.strip()))
        tag_objects = [Tag.objects.get_or_create(name=name)[0] for name in normalized]
        item.tags.set(tag_objects)

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        item = Item.objects.create(**validated_data)
        self._upsert_tags(item, tags)
        try:
            sync_item_embedding(item)
        except Exception:
            pass
        return item

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        self._upsert_tags(instance, tags)
        try:
            sync_item_embedding(instance)
        except Exception:
            pass
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tags"] = list(instance.tags.values_list("name", flat=True))
        request = self.context.get("request")
        if request and request.method != "GET":
            data.pop("comments", None)
        return data


def build_auth_response(user):
    refresh = RefreshToken.for_user(user)
    return {
        "accessToken": str(refresh.access_token),
        "refreshToken": str(refresh),
        "user": UserSerializer(user).data,
    }


class LostItemAssistantRequestSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=1000)
