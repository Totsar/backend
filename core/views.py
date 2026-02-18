from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from .models import Comment, Item, ItemReport
from .permissions import IsCommentAuthorOrReadOnly, IsItemOwnerOrReadOnly
from .serializers import (
    CommentSerializer,
    ItemSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    RegisterSerializer,
    VerifySerializer,
    build_auth_response,
)


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


class VerifyAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access_token = serializer.validated_data["accessToken"]

        try:
            UntypedToken(access_token)
        except TokenError:
            return Response({"detail": "Invalid access token."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_200_OK)


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
