from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Item
from .serializers import ItemSerializer
from .permissions import IsOwnerOrReadOnly

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    permission_classes = (IsOwnerOrReadOnly,)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permission() for permission in (IsOwnerOrReadOnly,)]
        return [permission() for permission in (IsAuthenticated, IsOwnerOrReadOnly)]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)