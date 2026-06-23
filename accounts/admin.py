from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin

from .models import Department, Designation, User


@admin.register(Designation)
class DesignationAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'slug', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Department)
class DepartmentAdmin(SimpleHistoryAdmin):
    list_display = ['name', 'slug', 'created_at']
    search_fields = ['name']
    prepopulated_fields = {'slug': ['name']}
    readonly_fields = ['created_at', 'updated_at']


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin, BaseUserAdmin):
    list_display = [
        'username', 'email', 'get_full_name', 'role',
        'designation', 'department', 'is_active', 'is_admin'
    ]
    list_filter = ['role', 'is_active', 'is_staff', 'is_superuser', 'department', 'designation']
    list_display_links = ['username', 'email']
    search_fields = ['username', 'email', 'first_name', 'last_name', 'mobile_number']
    ordering = ['username']
    filter_horizontal = ['groups', 'user_permissions', 'restaurants']

    readonly_fields = ['last_login', 'date_joined']

    fieldsets = [
        (
            'Login Credentials',
            {'fields': ['username', 'password']}
        ),
        (
            'Personal Info',
            {'fields': [('first_name', 'last_name'), 'email', 'mobile_number']}
        ),
        (
            'Role & Organization',
            {'fields': ['role', 'designation', 'department', 'manager', 'assigned_by']}
        ),
        (
            'Restaurants',
            {'fields': ['restaurants']}
        ),
        (
            'Permissions',
            {
                'fields': [
                    'is_active', 'is_staff', 'is_superuser',
                    'groups', 'user_permissions'
                ],
                'classes': ['collapse']
            }
        ),
        (
            'Important Dates',
            {'fields': ['last_login', 'date_joined'], 'classes': ['collapse']}
        ),
    ]

    add_fieldsets = [
        (
            None,
            {
                'classes': ['wide'],
                'fields': [
                    'username', 'email', 'password1', 'password2',
                    'role', 'designation', 'department',
                ],
            },
        ),
    ]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.user = request.user
        return form
