from django.contrib import admin

from .models import Campaign, MessageTemplate


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "reply_expected", "updated_at")
    list_filter = ("type",)
    search_fields = ("name", "body")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "status", "author", "updated_at")
    list_filter = ("status", "type")
    list_select_related = ("author",)
    search_fields = ("title", "body")
    filter_horizontal = ("floors", "rooms", "people", "excluded")
