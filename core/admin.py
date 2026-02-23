from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group

from .models import Comment, CommentReport, Item, ItemReport, Tag, User

admin.site.register(User, UserAdmin)
admin.site.register(Item)
admin.site.register(Tag)
admin.site.register(Comment)
admin.site.register(CommentReport)
admin.site.register(ItemReport)
admin.site.unregister(Group)
