from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export import resources
from simple_history.admin import SimpleHistoryAdmin

from accounts.models import User
from .models import Region, Restaurant


class RegionResource(resources.ModelResource):
    class Meta:
        model = Region
        fields = ['id', 'name', 'created_at', 'updated_at']
        import_id_fields = ['id']
        skip_unchanged = True


class RestaurantResource(resources.ModelResource):
    class Meta:
        model = Restaurant
        fields = [
            'id', 'code', 'name', 'region', 'city', 'address',
            'latitude', 'longitude', 'phone', 'manager_email',
            'status', 'opening_date', 'is_archived', 'created_at', 'updated_at'
        ]
        import_id_fields = ['code']
        skip_unchanged = True


@admin.register(Region)
class RegionAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [RegionResource]
    list_display = ['name', 'created_at']
    search_fields = ['name']
    ordering = ['name']
    readonly_fields = ['created_at', 'updated_at']


class RestaurantUserInline(admin.TabularInline):
    model = User.restaurants.through
    extra = 1
    verbose_name = "Assigned User"
    verbose_name_plural = "Assigned Users"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        field = super().formfield_for_foreignkey(db_field, request, **kwargs)
        if db_field.name == 'user':
            field.queryset = User.objects.filter(role='restaurant_user').select_related('designation')
            field.label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.email})"
        return field

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(Restaurant)
class RestaurantAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    inlines = [RestaurantUserInline]
    resource_classes = [RestaurantResource]
    list_display = [
        'code', 'name', 'city', 'region', 'status',
        'assigned_users', 'phone', 'opening_date', 'created_at'
    ]
    list_filter = ['status', 'city', 'region', 'opening_date']
    search_fields = ['code', 'name', 'city', 'phone', 'manager_email']
    ordering = ['city', 'name']
    readonly_fields = ['created_at', 'updated_at']
    list_select_related = ['region']

    def assigned_users(self, obj):
        users = obj.users.filter(is_active=True, role=User.Roles.RESTAURANT_USER).select_related('designation')
        return ', '.join(
            f"{u.get_full_name() or u.username}"
            for u in users
        ) or '—'
    assigned_users.short_description = 'Assigned Users'

    fieldsets = [
        (
            'Identifiers',
            {'fields': [('code', 'name')]}
        ),
        (
            'Location',
            {'fields': ['region', 'city', 'address', ('latitude', 'longitude')]}
        ),
        (
            'Contact',
            {'fields': ['phone', 'manager_email']}
        ),
        (
            'Status & Dates',
            {'fields': ['status', 'opening_date']}
        ),
        (
            'Timestamps',
            {'fields': ['created_at', 'updated_at'], 'classes': ['collapse']}
        ),
    ]
