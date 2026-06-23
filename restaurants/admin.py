from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Region, Restaurant


@admin.register(Region)
class RegionAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name']
    ordering = ['name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Restaurant)
class RestaurantAdmin(SimpleHistoryAdmin):
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
