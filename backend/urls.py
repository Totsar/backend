from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static

from core.views import (
    ItemCommentCreateAPIView,
    ItemCommentDetailAPIView,
    ItemDetailAPIView,
    ItemListCreateAPIView,
    ItemReportAPIView,
    LoginAPIView,
    LogoutAPIView,
    RequestRegisterOTPAPIView,
    RefreshAPIView,
    RegisterAPIView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/register/request-otp", RequestRegisterOTPAPIView.as_view(), name="register-request-otp"),
    path("api/auth/register", RegisterAPIView.as_view(), name="register"),
    path("api/auth/login", LoginAPIView.as_view(), name="login"),
    path("api/auth/logout", LogoutAPIView.as_view(), name="logout"),
    path("api/auth/refresh", RefreshAPIView.as_view(), name="refresh"),
    path("api/item", ItemListCreateAPIView.as_view(), name="item-list-create"),
    path("api/item/<int:item_id>", ItemDetailAPIView.as_view(), name="item-detail"),
    path("api/item/<int:item_id>/report", ItemReportAPIView.as_view(), name="item-report"),
    path("api/item/<int:item_id>/comment", ItemCommentCreateAPIView.as_view(), name="item-comment-create"),
    path(
        "api/item/<int:item_id>/comment/<int:comment_id>",
        ItemCommentDetailAPIView.as_view(),
        name="item-comment-detail",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
