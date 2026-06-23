from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import BusinessInfo, SocialMedia, Notification


class SocialMediaInline(admin.TabularInline):
    model = SocialMedia
    extra = 1


@admin.register(BusinessInfo)
class BusinessInfoAdmin(SimpleHistoryAdmin):
    inlines = [SocialMediaInline]
    list_display = ('company_name', 'phone', 'email')

    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SocialMedia)
class SocialMediaAdmin(SimpleHistoryAdmin):
    list_display = ('platform', 'business', 'url', 'order')
    list_editable = ('order',)
    list_filter = ('platform',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'title', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('recipient__username', 'recipient__email', 'title')
    readonly_fields = ('created_at', 'updated_at')
