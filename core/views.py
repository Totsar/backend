import json

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .ai_assistant import find_lost_items_with_ai
from .models import Comment, Item, ItemReport
from .permissions import IsCommentAuthorOrReadOnly, IsItemOwnerOrReadOnly
from .serializers import (
    CommentSerializer,
    ItemSerializer,
    LoginSerializer,
    LogoutSerializer,
    RequestRegisterOTPSerializer,
    RefreshSerializer,
    RegisterSerializer,
    LostItemAssistantRequestSerializer,
    build_auth_response,
)


class RequestRegisterOTPAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestRegisterOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "OTP sent successfully."}, status=status.HTTP_200_OK)


class RegisterAPIView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(build_auth_response(user), status=status.HTTP_201_CREATED)


class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        return Response(build_auth_response(user), status=status.HTTP_200_OK)


class LogoutAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data["refreshToken"]

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data["refreshToken"]

        try:
            token = RefreshToken(refresh_token)
            access = token.access_token
        except TokenError:
            return Response({"detail": "Invalid refresh token."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"accessToken": str(access)}, status=status.HTTP_200_OK)


class ItemListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ItemSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Item.objects.select_related("owner").prefetch_related("tags", "comments__user").all()
        search = self.request.query_params.get("search")
        tag = self.request.query_params.get("tag")
        owner = self.request.query_params.get("owner")

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(location__icontains=search)
            )
        if tag:
            queryset = queryset.filter(tags__name__iexact=tag)
        if owner:
            queryset = queryset.filter(owner_id=owner)

        return queryset.distinct().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ItemDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ItemSerializer
    permission_classes = [IsItemOwnerOrReadOnly]
    queryset = Item.objects.select_related("owner").prefetch_related("tags", "comments__user").all()
    lookup_url_kwarg = "item_id"


class ItemReportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, item_id):
        item = get_object_or_404(Item, pk=item_id)
        ItemReport.objects.get_or_create(item=item, user=request.user)
        return Response(status=status.HTTP_201_CREATED)


class ItemCommentCreateAPIView(generics.CreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        item = get_object_or_404(Item, pk=self.kwargs["item_id"])
        serializer.save(item=item, user=self.request.user)


class ItemCommentDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsCommentAuthorOrReadOnly]
    lookup_url_kwarg = "comment_id"

    def get_queryset(self):
        return Comment.objects.filter(item_id=self.kwargs["item_id"]).select_related("user")


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class LostItemAssistantAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LostItemAssistantRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = find_lost_items_with_ai(query=serializer.validated_data["query"])
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            return Response(
                {"detail": "The assistant is currently unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": result["message"],
                "pickedItemIds": result["picked_item_ids"],
                "candidateItemIds": result["candidate_item_ids"],
            },
            status=status.HTTP_200_OK,
        )


class LostItemAssistantStreamAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LostItemAssistantRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = find_lost_items_with_ai(query=serializer.validated_data["query"])
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            return Response(
                {"detail": "The assistant is currently unavailable. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        message = result["message"]
        picked_ids = result["picked_item_ids"]
        candidate_ids = result["candidate_item_ids"]

        def stream():
            chunk_size = 80
            for i in range(0, len(message), chunk_size):
                yield _sse_event("assistant_message", {"chunk": message[i : i + chunk_size]})
            yield _sse_event("selected_item_ids", {"itemIds": picked_ids})
            yield _sse_event("candidate_item_ids", {"itemIds": candidate_ids})
            yield _sse_event("done", {})

        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["Connection"] = "keep-alive"
        response["X-Accel-Buffering"] = "no"
        return response
