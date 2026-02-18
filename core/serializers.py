from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Comment, Item, Tag


User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    firstName = serializers.CharField(source="first_name")
    lastName = serializers.CharField(source="last_name")

    class Meta:
        model = User
        fields = ["id", "firstName", "lastName", "email", "phone"]


class RegisterSerializer(serializers.Serializer):
    firstName = serializers.CharField(max_length=150)
    lastName = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        normalized = value.lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def create(self, validated_data):
        email = validated_data["email"]
        return User.objects.create_user(
            username=email,
            email=email,
            first_name=validated_data["firstName"],
            last_name=validated_data["lastName"],
            phone=validated_data.get("phone", ""),
            password=validated_data["password"],
        )


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


class VerifySerializer(serializers.Serializer):
    accessToken = serializers.CharField()


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
            "createdAt",
            "tags",
            "comments",
        ]

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
        return item

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        self._upsert_tags(instance, tags)
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
