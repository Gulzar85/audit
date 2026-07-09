from django.contrib import admin
from import_export.admin import ImportExportModelAdmin
from import_export import resources
from simple_history.admin import SimpleHistoryAdmin

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


@admin.register(Restaurant)
class RestaurantAdmin(ImportExportModelAdmin, SimpleHistoryAdmin):
    resource_classes = [RestaurantResource]
    list_display = [
        'code', 'name', 'city', 'region', 'status',
        'phone', 'opening_date', 'created_at'
    ]
    list_filter = ['status', 'city', 'region', 'opening_date']
    search_fields = ['code', 'name', 'city', 'phone', 'manager_email']
    ordering = ['city', 'name']
    readonly_fields = ['created_at', 'updated_at']
    list_select_related = ['region']
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
